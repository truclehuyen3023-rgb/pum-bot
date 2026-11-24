import asyncio
import math
import random
import sqlite3
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
from ores import ITEMS, PICKAXES, get_adjusted_weights

import os
from aiohttp import web


async def _health_check(request: web.Request) -> web.Response:
    return web.Response(text="OK", status=200)


async def start_keep_alive() -> None:
    app = web.Application()
    app.router.add_get("/", _health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Keep-alive đang mở cổng {port}")

VN_TZ = timezone(timedelta(hours=7))

RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]
RARITY_LABELS = {
    "Common": "Phổ Thông (Common)",
    "Uncommon": "Ít Gặp (Uncommon)",
    "Rare": "Hiếm (Rare)",
    "Epic": "Sử Thi (Epic)",
    "Legendary": "Huyền Thoại (Legendary)",
    "Mythic": "Thần Thoại (Mythic)",
}
RARITY_BADGES = {
    "Common": "⚪ Common",
    "Uncommon": "🟢 Uncommon",
    "Rare": "🔵 Rare",
    "Epic": "🟣 Epic",
    "Legendary": "🟡 Legendary",
    "Mythic": "🔴 Mythic",
}
RARITY_COLORS = {
    "Common": discord.Color.light_grey(),
    "Uncommon": discord.Color.green(),
    "Rare": discord.Color.blue(),
    "Epic": discord.Color.purple(),
    "Legendary": discord.Color.gold(),
    "Mythic": discord.Color.red(),
}

REPAIR_GOLD_COST = {
    1: 45,
    2: 110,
    3: 240,
    4: 480,
}

# --- KHỞI TẠO DATABASE ---
conn = sqlite3.connect("mining_v2.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS miners (
    user_id INTEGER PRIMARY KEY,
    gold INTEGER DEFAULT 100,
    miner_level INTEGER DEFAULT 1,
    miner_xp INTEGER DEFAULT 0,
    pickaxe_level INTEGER DEFAULT 1,
    durability INTEGER DEFAULT 30,
    total_mines INTEGER DEFAULT 0,
    chests INTEGER DEFAULT 0,
    basin_water INTEGER DEFAULT 0,
    last_reset_day TEXT DEFAULT '',
    daily_claimed INTEGER DEFAULT 0,
    q_mines INTEGER DEFAULT 0,
    q_chests INTEGER DEFAULT 0,
    q_repairs INTEGER DEFAULT 0,
    q_sells INTEGER DEFAULT 0,
    q_water_filled INTEGER DEFAULT 0,
    q_claimed_mask INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER,
    item_name TEXT,
    quantity INTEGER,
    PRIMARY KEY (user_id, item_name)
)
""")
conn.commit()


# --- CHU KỲ RESET 07:00 SÁNG GIỜ VIỆT NAM ---
def current_game_day() -> str:
    now_vn = datetime.now(VN_TZ)
    shifted = now_vn - timedelta(hours=7)
    return shifted.strftime("%Y-%m-%d")


def next_reset_timestamp() -> int:
    now_vn = datetime.now(VN_TZ)
    target = now_vn.replace(hour=7, minute=0, second=0, microsecond=0)
    if now_vn >= target:
        target += timedelta(days=1)
    return int(target.timestamp())


# --- HÀM DATABASE & TIẾN ĐỘ ---
def ensure_miner(user_id: int) -> None:
    today = current_game_day()
    cursor.execute(
        """
        INSERT OR IGNORE INTO miners (user_id, gold, miner_level, miner_xp, pickaxe_level, durability, last_reset_day)
        VALUES (?, 100, 1, 0, 1, 30, ?)
        """,
        (user_id, today),
    )
    cursor.execute("SELECT last_reset_day FROM miners WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] != today:
        cursor.execute(
            """
            UPDATE miners
            SET last_reset_day = ?,
                daily_claimed = 0,
                q_mines = 0,
                q_chests = 0,
                q_repairs = 0,
                q_sells = 0,
                q_water_filled = 0,
                q_claimed_mask = 0
            WHERE user_id = ?
            """,
            (today, user_id),
        )
    conn.commit()


def get_miner_row(user_id: int) -> dict:
    ensure_miner(user_id)
    cursor.execute(
        """
        SELECT gold, miner_level, miner_xp, pickaxe_level, durability, total_mines,
               chests, basin_water, daily_claimed, q_mines, q_chests, q_repairs,
               q_sells, q_water_filled, q_claimed_mask
        FROM miners WHERE user_id = ?
        """,
        (user_id,),
    )
    r = cursor.fetchone()
    keys = [
        "gold", "miner_level", "miner_xp", "pickaxe_level", "durability", "total_mines",
        "chests", "basin_water", "daily_claimed", "q_mines", "q_chests", "q_repairs",
        "q_sells", "q_water_filled", "q_claimed_mask",
    ]
    return dict(zip(keys, r))


def add_gold(user_id: int, amount: int) -> None:
    ensure_miner(user_id)
    cursor.execute("UPDATE miners SET gold = MAX(0, gold + ?) WHERE user_id = ?", (amount, user_id))
    conn.commit()


def add_xp(user_id: int, xp_gain: int) -> tuple[bool, int]:
    data = get_miner_row(user_id)
    lv = data["miner_level"]
    xp = data["miner_xp"] + xp_gain
    leveled_up = False
    while xp >= lv * 100:
        xp -= lv * 100
        lv += 1
        leveled_up = True
    cursor.execute("UPDATE miners SET miner_level = ?, miner_xp = ? WHERE user_id = ?", (lv, xp, user_id))
    conn.commit()
    return leveled_up, lv


def get_item_qty(user_id: int, item_name: str) -> int:
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    row = cursor.fetchone()
    return row[0] if row else 0


def add_item(user_id: int, item_name: str, amount: int) -> None:
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?",
            (amount, user_id, item_name),
        )
    else:
        cursor.execute(
            "INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)",
            (user_id, item_name, amount),
        )
    conn.commit()


def remove_item(user_id: int, item_name: str, amount: int) -> bool:
    owned = get_item_qty(user_id, item_name)
    if owned < amount:
        return False
    if owned == amount:
        cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
    else:
        cursor.execute(
            "UPDATE inventory SET quantity = quantity - ? WHERE user_id = ? AND item_name = ?",
            (amount, user_id, item_name),
        )
    conn.commit()
    return True


def get_drop_chance_map(pickaxe_level: int) -> dict[str, float]:
    names, weights = get_adjusted_weights(pickaxe_level)
    total_w = sum(weights)
    if total_w <= 0:
        return {}
    return {name: (w / total_w) * 100.0 for name, w in zip(names, weights)}


def pick_distinct_ores(pickaxe_level: int, count: int) -> list[str]:
    names, weights = get_adjusted_weights(pickaxe_level)
    pool_names = list(names)
    pool_weights = list(weights)
    chosen: list[str] = []

    target_count = min(count, len(pool_names))
    for _ in range(target_count):
        if not pool_names or sum(pool_weights) <= 0:
            break
        picked = random.choices(pool_names, weights=pool_weights, k=1)[0]
        chosen.append(picked)
        idx = pool_names.index(picked)
        pool_names.pop(idx)
        pool_weights.pop(idx)

    return chosen


def get_sellable_ores(user_id: int) -> list[tuple[str, int, dict]]:
    cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (user_id,))
    rows = cursor.fetchall()
    result = []
    for item_name, qty in rows:
        info = ITEMS.get(item_name)
        if info and info.get("category") == "ore":
            result.append((item_name, qty, info))
    return result


def get_daily_quests(data: dict) -> list[tuple[int, str, int, int, int, int]]:
    return [
        (1, "Đào mỏ đủ 20 lần", min(data["q_mines"], 20), 20, 150, 30),
        (2, "Kiếm đủ 5 rương trong ngày", min(data["q_chests"], 5), 5, 200, 40),
        (4, "Sửa chữa cuốc 1 lần", min(data["q_repairs"], 1), 1, 120, 25),
        (8, "Nạp Mạch Nước Ngầm vào Bình Cổ (120l)", min(data["basin_water"], 120), 120, 300, 50),
        (16, "Bán đồ cho Chủ Lò Rèn 5 lần", min(data["q_sells"], 5), 5, 180, 35),
    ]


# --- LOGIC XỬ LÝ TƯƠNG TÁC ---
def perform_basin_sacrifice(user_id: int) -> tuple[bool, str]:
    data = get_miner_row(user_id)
    owned_water = get_item_qty(user_id, "Mạch Nước Ngầm")
    current_basin = data["basin_water"]

    if current_basin >= 120:
        return False, "Bình Cổ ở bệ đá giữa hang đã đầy **`120/120l`**."
    if owned_water <= 0:
        return False, "Trong túi chưa có **Mạch Nước Ngầm** nào để hiến tế."

    need = 120 - current_basin
    to_pour = min(owned_water, need)
    remove_item(user_id, "Mạch Nước Ngầm", to_pour)
    new_basin = current_basin + to_pour

    cursor.execute(
        "UPDATE miners SET basin_water = ?, q_water_filled = ? WHERE user_id = ?",
        (new_basin, new_basin, user_id),
    )
    conn.commit()

    bonus_text = ""
    if new_basin >= 120:
        add_gold(user_id, 350)
        add_xp(user_id, 60)
        bonus_text = "\n✨ Bình Cổ đầy nước (`120/120l`) — nhận **`+350 Vàng`** & **`+60 XP`**."

    return True, f"Đã hiến tế **`{to_pour}l` Mạch Nước Ngầm** vào Bình Cổ (**`{new_basin}/120l`**).{bonus_text}"


def perform_repair_with_gold(user_id: int) -> tuple[bool, str]:
    data = get_miner_row(user_id)
    pick_lv = data["pickaxe_level"]
    pick = PICKAXES.get(pick_lv, PICKAXES[1])
    cost = REPAIR_GOLD_COST.get(pick_lv, 50)

    if data["durability"] >= pick["max_durability"]:
        return False, f"**{pick['name']}** đang đầy độ bền (`{data['durability']}/{pick['max_durability']}`)."

    if data["gold"] < cost:
        return False, f"Cần **`{cost:,} Vàng`** để sửa **{pick['name']}** (hiện có `{data['gold']:,}` Vàng)."

    add_gold(user_id, -cost)
    cursor.execute(
        "UPDATE miners SET durability = ?, q_repairs = q_repairs + 1 WHERE user_id = ?",
        (pick["max_durability"], user_id),
    )
    conn.commit()
    return True, f"Đã sửa **{pick['name']}** (`{pick['max_durability']}/{pick['max_durability']}`) • Trừ **`{cost:,} Vàng`**."


def perform_sell_all_wagon(user_id: int) -> tuple[bool, str]:
    ensure_miner(user_id)
    sellables = get_sellable_ores(user_id)
    if not sellables:
        return False, "Không có quặng nào trên xe để bán *(Mạch Nước Ngầm không bán được)*."

    total_earned = 0
    sold_summary = []
    for ore_name, qty, info in sellables:
        line_val = qty * info["value"]
        total_earned += line_val
        unit_str = f"{qty}{info['unit']}" if info["unit"] == "l" else f"{qty} {info['unit']}"
        sold_summary.append(f"{info['emoji']} {ore_name} ×`{unit_str}` (`+{line_val:,}`)")
        cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, ore_name))

    cursor.execute("UPDATE miners SET q_sells = q_sells + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    add_gold(user_id, total_earned)

    return True, (
        f"Đã bán cả xe quặng và nhận **`+{total_earned:,} Vàng`**:\n"
        + "\n".join(sold_summary)
    )


def perform_sell_specific(user_id: int, ore_name: str, qty_to_sell: int) -> tuple[bool, str]:
    ensure_miner(user_id)
    info = ITEMS.get(ore_name)
    if not info or info.get("category") != "ore":
        return False, "Vật phẩm này không thể bán cho Chủ Lò Rèn."

    owned = get_item_qty(user_id, ore_name)
    if owned < qty_to_sell or qty_to_sell <= 0:
        return False, f"Chỉ có **`{owned}` {info['unit']} {ore_name}** trong túi."

    remove_item(user_id, ore_name, qty_to_sell)
    earned = qty_to_sell * info["value"]
    add_gold(user_id, earned)
    cursor.execute("UPDATE miners SET q_sells = q_sells + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

    unit_str = f"{qty_to_sell}{info['unit']}" if info["unit"] == "l" else f"{qty_to_sell} {info['unit']}"
    return True, f"Đã bán **`{unit_str}` {ore_name}** • Nhận **`+{earned:,} Vàng`**."


# --- UI NÚT TƯƠNG TÁC: BÌNH CỔ ---
class AncientUrnView(discord.ui.View):
    def __init__(self, owner_id: int, water_qty: int) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id

        sacrifice_btn = discord.ui.Button(
            label=f"> hiến tế {water_qty}l" if water_qty > 0 else "> hiến tế 0l",
            style=discord.ButtonStyle.primary,
            disabled=(water_qty <= 0),
        )
        sacrifice_btn.callback = self.on_sacrifice
        self.add_item(sacrifice_btn)

        leave_btn = discord.ui.Button(
            label="> rời đi",
            style=discord.ButtonStyle.secondary,
        )
        leave_btn.callback = self.on_leave
        self.add_item(leave_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Chỉ chủ nhân lượt gọi mới tương tác được.", ephemeral=True)
            return False
        return True

    async def on_sacrifice(self, interaction: discord.Interaction) -> None:
        ok, msg = perform_basin_sacrifice(self.owner_id)
        data = get_miner_row(self.owner_id)
        remain_w = get_item_qty(self.owner_id, "Mạch Nước Ngầm")
        new_view = AncientUrnView(self.owner_id, remain_w)

        embed = discord.Embed(
            title="🏺 Bình Cổ",
            description=f"*tiếng kêu khẽ của nước*\n\nBình Cổ: **`{data['basin_water']}/120l`** • Nước còn lại: **`{remain_w}l`**\n\n{msg}",
            color=discord.Color.teal() if ok else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=new_view)

    async def on_leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Rời khỏi bệ đá giữa hang.", embed=None, view=None)


# --- UI NÚT TƯƠNG TÁC: CHỦ LÒ RÈN ---
class SellQuantityModal(discord.ui.Modal):
    qty_input = discord.ui.TextInput(
        label="Số lượng muốn bán (hoặc gõ 'all')",
        placeholder="Ví dụ: 5 hoặc all",
        required=True,
        max_length=10,
    )

    def __init__(self, owner_id: int, ore_name: str, owned: int, unit_price: int) -> None:
        super().__init__(title=f"Bán {ore_name} ({unit_price} Vàng/đơn vị)")
        self.owner_id = owner_id
        self.ore_name = ore_name
        self.owned = owned
        self.unit_price = unit_price

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.qty_input.value.strip().lower()
        if raw == "all":
            qty = self.owned
        elif raw.isdigit() and int(raw) > 0:
            qty = int(raw)
        else:
            await interaction.response.send_message("Số lượng không hợp lệ. Nhập số dương hoặc `all`.", ephemeral=True)
            return

        ok, msg = perform_sell_specific(self.owner_id, self.ore_name, qty)
        embed = discord.Embed(
            title="⚒️ Chủ Lò Rèn",
            description=f"Chủ: Bạn muốn gì?\n\n{msg}",
            color=discord.Color.gold() if ok else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=BlacksmithMainView(self.owner_id))


class OreSelectMenu(discord.ui.Select):
    def __init__(self, owner_id: int, sellables: list[tuple[str, int, dict]]) -> None:
        self.owner_id = owner_id
        options = []
        for ore_name, qty, info in sellables[:25]:
            unit_lbl = f"{qty}{info['unit']}" if info["unit"] == "l" else f"{qty} {info['unit']}"
            options.append(
                discord.SelectOption(
                    label=f"{ore_name} ({unit_lbl})",
                    description=f"Giá: {info['value']} Vàng • Tổng: {qty * info['value']:,} Vàng",
                    value=ore_name,
                    emoji=info["emoji"],
                )
            )
        super().__init__(placeholder="Chọn loại quặng muốn bán...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        ore_name = self.values[0]
        owned = get_item_qty(self.owner_id, ore_name)
        unit_price = ITEMS[ore_name]["value"]
        await interaction.response.send_modal(SellQuantityModal(self.owner_id, ore_name, owned, unit_price))


class SellBranchView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id
        sellables = get_sellable_ores(owner_id)
        if sellables:
            self.add_item(OreSelectMenu(owner_id, sellables))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Chỉ chủ nhân lượt gọi mới tương tác được.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="> bán từng quặng", style=discord.ButtonStyle.primary)
    async def sell_one_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        sellables = get_sellable_ores(self.owner_id)
        if not sellables:
            await interaction.response.send_message("Túi hiện không có quặng nào để bán.", ephemeral=True)
            return
        lines = [
            f"{info['emoji']} **{name}** — `{qty}` • `{info['value']}` Vàng/đơn vị"
            for name, qty, info in sellables
        ]
        embed = discord.Embed(
            title="⚒️ Chủ Lò Rèn — Bán Từng Quặng",
            description="Chọn loại quặng ở menu bên dưới để nhập số lượng:\n\n" + "\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=SellBranchView(self.owner_id))

    @discord.ui.button(label="> bán cả xe quặng", style=discord.ButtonStyle.success)
    async def sell_wagon_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ok, msg = perform_sell_all_wagon(self.owner_id)
        embed = discord.Embed(
            title="⚒️ Chủ Lò Rèn — Bán Cả Xe Quặng",
            description=f"Chủ: Bạn muốn gì?\n\n{msg}",
            color=discord.Color.gold() if ok else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=BlacksmithMainView(self.owner_id))

    @discord.ui.button(label="> quay lại", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="⚒️ Chủ Lò Rèn",
            description="Chủ: Bạn muốn gì?",
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=BlacksmithMainView(self.owner_id))


class BlacksmithMainView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id
        data = get_miner_row(owner_id)
        pick_name = PICKAXES.get(data["pickaxe_level"], PICKAXES[1])["name"]
        repair_cost = REPAIR_GOLD_COST.get(data["pickaxe_level"], 50)

        repair_btn = discord.ui.Button(
            label=f"> sửa cuốc {pick_name} ({repair_cost}g)",
            style=discord.ButtonStyle.primary,
        )
        repair_btn.callback = self.on_repair
        self.add_item(repair_btn)

        sell_btn = discord.ui.Button(
            label="> bán quặng",
            style=discord.ButtonStyle.success,
        )
        sell_btn.callback = self.on_sell_menu
        self.add_item(sell_btn)

        leave_btn = discord.ui.Button(
            label="> rời đi",
            style=discord.ButtonStyle.secondary,
        )
        leave_btn.callback = self.on_leave
        self.add_item(leave_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Chỉ chủ nhân lượt gọi mới tương tác được.", ephemeral=True)
            return False
        return True

    async def on_repair(self, interaction: discord.Interaction) -> None:
        ok, msg = perform_repair_with_gold(self.owner_id)
        embed = discord.Embed(
            title="⚒️ Chủ Lò Rèn",
            description=f"Chủ: Bạn muốn gì?\n\n{msg}",
            color=discord.Color.teal() if ok else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=BlacksmithMainView(self.owner_id))

    async def on_sell_menu(self, interaction: discord.Interaction) -> None:
        sellables = get_sellable_ores(self.owner_id)
        if not sellables:
            embed = discord.Embed(
                title="⚒️ Chủ Lò Rèn",
                description="Chủ: Bạn muốn gì?\n\nKhông có quặng nào trong túi để bán.",
                color=discord.Color.red(),
            )
            await interaction.response.edit_message(embed=embed, view=BlacksmithMainView(self.owner_id))
            return

        lines = [
            f"{info['emoji']} **{name}** — `{qty}` • `{info['value']}` Vàng/đơn vị (`{qty * info['value']:,}` Vàng)"
            for name, qty, info in sellables
        ]
        embed = discord.Embed(
            title="⚒️ Chủ Lò Rèn — Chọn Cách Bán",
            description="Chủ: Bạn muốn bán từng loại hay bán cả xe quặng?\n\n" + "\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=SellBranchView(self.owner_id))

    async def on_leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Rời khỏi lò rèn.", embed=None, view=None)


# --- UI TƯƠNG TÁC CHI TIẾT: p help ---
class HelpCategoryView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=90)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Chỉ chủ nhân lượt gọi mới tương tác được.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⛏️ Đào & Kho Đồ", style=discord.ButtonStyle.primary)
    async def mine_bag_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="⛏️ HƯỚNG DẪN ĐÀO MỎ, RƯƠNG & KHO ĐỒ",
            description=(
                "Mỗi nhát cuốc có thể khui ra nhiều loại quặng/tài nguyên khác nhau cùng lúc, kèm độ hiếm và `%` xác suất rớt."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="• `p mine` (`p m`, `p dao`) — Khai thác tài nguyên",
            value=(
                "• Trừ **1 độ bền** cuốc mỗi lần đào; về `0` sẽ không đào được cho tới khi sửa.\n"
                "• Có thể rớt nhiều loại khoáng sản/nước ngầm trong 1 lượt (tăng theo cấp cuốc).\n"
                "• Cooldown đếm ngược từng giây và tự xóa thông báo chờ khi hết giờ.\n"
                "• Có cơ hội nhặt **Rương Kho Báu** (tối đa **5 rương/ngày**)."
            ),
            inline=False,
        )
        embed.add_field(
            name="• `p bag` (`p inv`, `p tui`) — Xem túi & chỉ số",
            value=(
                "• Hiển thị Vàng, Cấp Thợ Mỏ (`Lv.`), XP, lãi suất điểm danh ngày, độ bền cuốc hiện tại và trạng thái **Bình Cổ (`120l`)**.\n"
                "• Quặng và tài nguyên được xếp theo độ hiếm từ cao xuống thấp kèm icon và số lượng."
            ),
            inline=False,
        )
        embed.add_field(
            name="• `p chest [số/all]` (`p ruong`) — Mở rương",
            value=(
                "• Mở rương để lấy nguyên liệu rèn/nâng cấp cuốc (`Đá Mài Thô`, `Phôi Sắt Gia Cường`, `Lõi Tinh Thể Cổ`).\n"
                "• Có tỷ lệ nhỏ rớt thẳng thêm Vàng."
            ),
            inline=False,
        )
        embed.add_field(
            name="• `p top` (`p lb`, `p bxh`) — Bảng xếp hạng",
            value="• Xếp hạng Top 10 thợ mỏ có nhiều Vàng nhất cùng cấp Thợ Mỏ và cấp Cuốc.",
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏺 Bình Cổ & Lò Rèn", style=discord.ButtonStyle.success)
    async def npc_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="🏺 TƯƠNG TÁC BÌNH CỔ & CHỦ LÒ RÈN",
            description="Các điểm tương tác sử dụng nút bấm trực tiếp — không cần nhớ cú pháp dài dòng.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="• `p fill` (`p binh`, `p nap`) — Bình Cổ bệ đá giữa hang",
            value=(
                "• **Mạch Nước Ngầm** tính theo **lít (`l`)**, không bán ra tiền được.\n"
                "• Bấm **`> hiến tế [số nước]l`** để rót nước vào Bình Cổ (tổng sức chứa **`120l`**).\n"
                "• Khi nạp đủ **`120/120l`** sẽ thanh tẩy bệ đá thành công và nhận thưởng Vàng + XP."
            ),
            inline=False,
        )
        embed.add_field(
            name="• `p forge` (`p b`, `p sell`, `p ban`) — Chủ Lò Rèn",
            value=(
                "• **`> sửa cuốc [tên cuốc]`**: Hồi đầy độ bền cuốc bằng Vàng theo cấp cuốc (`Lv.1: 45g` • `Lv.2: 110g` • `Lv.3: 240g` • `Lv.4: 480g`).\n"
                "• **`> bán quặng`** — Chia làm **2 nhánh**:\n"
                "  1. **Bán từng quặng**: Chọn loại quặng trong danh sách -> nhập số lượng (hoặc `all`) -> nhận Vàng đúng theo `số lượng × giá`.\n"
                "  2. **Bán cả xe quặng**: Bán toàn bộ quặng trong túi chỉ với 1 nút bấm.\n"
                "• **`> rời đi`**: Đóng khung hội thoại."
            ),
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📅 Daily & Nâng Cấp", style=discord.ButtonStyle.secondary)
    async def daily_shop_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="📅 DAILY, 5 NHIỆM VỤ NGÀY & NÂNG CẤP CUỐC",
            description="Toàn bộ điểm danh và nhiệm vụ ngày tự động reset vào **07:00 sáng** (giờ Việt Nam).",
            color=discord.Color.teal(),
        )
        embed.add_field(
            name="• `p daily` (`p nv`, `p quest`) & `p claim` (`p nhan`)",
            value=(
                "• **Điểm danh ngày**: Cộng Vàng theo lãi suất tăng dần theo cấp Thợ Mỏ (`1.0% + Level × 0.1%`, ví dụ Lv.1 `+1.1%`, Lv.2 `+1.2%`...) kèm XP.\n"
                "• **5 Nhiệm vụ ngày** (hoàn thành xong gõ `p claim` để nhận thưởng):\n"
                "  1. Đào mỏ đủ **20 lần**\n"
                "  2. Kiếm đủ **5 rương** trong ngày\n"
                "  3. Sửa chữa cuốc **1 lần**\n"
                "  4. Nạp Mạch Nước Ngầm vào Bình Cổ (**120l**)\n"
                "  5. Bán đồ cho Chủ Lò Rèn **5 lần**"
            ),
            inline=False,
        )
        embed.add_field(
            name="• `p shop` (`p cuahang`) & `p buy` (`p mua`)",
            value=(
                "• Xem yêu cầu Vàng + nguyên liệu từ rương để rèn cuốc cấp cao hơn.\n"
                "• Cuốc cấp cao tăng độ bền tối đa, tăng sản lượng quặng/nước ngầm và nhân hệ số quặng hiếm."
            ),
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=self)


# --- SETUP BOT (PREFIX "p ") ---
intents = discord.Intents.default()
intents.message_content = True

class PickaxeBot(commands.Bot):
    async def setup_hook(self) -> None:
        self.loop.create_task(start_keep_alive())
        
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("p ", "P "),
    intents=intents,
    help_command=None,
)


@bot.event
async def on_ready() -> None:
    print(f"PickaxeCore đã online: {bot.user}")


@bot.command(name="mine", aliases=["m", "dao"])
@commands.cooldown(1, 10.0, commands.BucketType.user)
async def mine(ctx: commands.Context) -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    pick_lv = data["pickaxe_level"]
    pick = PICKAXES.get(pick_lv, PICKAXES[1])

    if data["durability"] <= 0:
        ctx.command.reset_cooldown(ctx)
        await ctx.reply(
            f"💥 **{pick['name']}** hết độ bền (`0/{pick['max_durability']}`). Dùng `p forge` để sửa cuốc."
        )
        return

    new_dur = max(0, data["durability"] - 1)
    cursor.execute(
        "UPDATE miners SET total_mines = total_mines + 1, q_mines = q_mines + 1, durability = ? WHERE user_id = ?",
        (new_dur, uid),
    )
    conn.commit()

    chest_note = ""
    if data["q_chests"] < 5 and random.random() < 0.28:
        cursor.execute(
            "UPDATE miners SET chests = chests + 1, q_chests = q_chests + 1 WHERE user_id = ?",
            (uid,),
        )
        conn.commit()
        chest_note = f"\n🎁 **Rương Kho Báu**: `+1` (`{data['q_chests'] + 1}/5` hôm nay) — `p chest`"

    if random.random() < 0.08:
        leveled, new_lv = add_xp(uid, 5)
        lv_msg = f" • 🎉 Lv.{new_lv}" if leveled else ""
        await ctx.reply(
            f"⛏️ Không đào được gì • Độ bền: `{new_dur}/{pick['max_durability']}`{lv_msg}{chest_note}"
        )
        return

    max_types = min(4, 2 + (pick_lv // 2))
    type_roll = random.random()
    if type_roll < 0.35:
        num_types = 1
    elif type_roll < 0.82 or max_types == 2:
        num_types = 2
    else:
        num_types = random.randint(3, max_types)

    picked_names = pick_distinct_ores(pick_lv, num_types)
    chance_map = get_drop_chance_map(pick_lv)

    drops: list[tuple[str, int, dict, float]] = []
    for item_name in picked_names:
        info = ITEMS[item_name]
        if info["category"] == "water":
            amount = random.randint(pick["water_min"], pick["water_max"])
        else:
            amount = random.randint(pick["bonus_min"], pick["bonus_max"])
        if num_types >= 3:
            amount = max(1, amount)
        add_item(uid, item_name, amount)
        drops.append((item_name, amount, info, chance_map.get(item_name, 0.0)))

    leveled, new_lv = add_xp(uid, 10 + 4 * len(drops))
    rarity_rank = {r: idx for idx, r in enumerate(RARITY_ORDER)}
    highest_rarity = max((d[2]["rarity"] for d in drops), key=lambda r: rarity_rank.get(r, 0))

    lines = []
    for item_name, amount, info, drop_pct in drops:
        unit = info["unit"]
        qty_str = f"{amount}{unit}" if unit == "l" else f"{amount} {unit}"
        badge = RARITY_BADGES.get(info["rarity"], "⚪ Common")
        if info["category"] == "water":
            extra = "• *Nạp Bình Cổ*"
        else:
            extra = f"• `{info['value']}` Vàng/{unit}"
        lines.append(f"{info['emoji']} **{item_name}** ×`{qty_str}` • {badge} (`{drop_pct:.1f}%`) {extra}")

    if chest_note:
        lines.append(chest_note)

    embed = discord.Embed(
        title=f"⛏️ Kết quả đào ({len(drops)} loại)",
        description="\n".join(lines),
        color=RARITY_COLORS.get(highest_rarity, discord.Color.blurple()),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    lv_text = f" • 🎉 Lv.{new_lv}" if leveled else ""
    embed.set_footer(
        text=f"Lv.{new_lv} • {pick['name']} ({new_dur}/{pick['max_durability']}) • #{data['total_mines'] + 1}{lv_text}"
    )
    await ctx.reply(embed=embed)


@mine.error
async def mine_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandOnCooldown):
        remaining = max(1, math.ceil(error.retry_after))
        msg = await ctx.reply(f"⏳ Đợi **{remaining}s**...")
        while remaining > 1:
            await asyncio.sleep(1)
            remaining -= 1
            try:
                await msg.edit(content=f"⏳ Đợi **{remaining}s**...")
            except discord.HTTPException:
                break
        await asyncio.sleep(1)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass


@bot.command(name="fill", aliases=["binh", "urn", "nap"])
async def fill(ctx: commands.Context) -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    water_qty = get_item_qty(uid, "Mạch Nước Ngầm")
    embed = discord.Embed(
        title="🏺 Bình Cổ",
        description=f"*tiếng kêu khẽ của nước*\n\nBình Cổ: **`{data['basin_water']}/120l`** • Nước hiện có: **`{water_qty}l`**",
        color=discord.Color.teal(),
    )
    await ctx.reply(embed=embed, view=AncientUrnView(uid, water_qty))


@bot.command(name="forge", aliases=["b", "blacksmith", "sell", "ban"])
async def forge(ctx: commands.Context) -> None:
    uid = ctx.author.id
    ensure_miner(uid)
    embed = discord.Embed(
        title="⚒️ Chủ Lò Rèn",
        description="Chủ: Bạn muốn gì?",
        color=discord.Color.gold(),
    )
    await ctx.reply(embed=embed, view=BlacksmithMainView(uid))


@bot.command(name="bag", aliases=["inv", "tui"])
async def bag(ctx: commands.Context) -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    pick_lv = data["pickaxe_level"]
    pick = PICKAXES.get(pick_lv, PICKAXES[1])

    cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ? AND quantity > 0", (uid,))
    rows = cursor.fetchall()

    embed = discord.Embed(
        title=f"🎒 Kho Đồ của {ctx.author.display_name}",
        color=discord.Color.gold(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    interest_pct = 1.0 + data["miner_level"] * 0.1
    embed.add_field(name="💰 Vàng", value=f"**{data['gold']:,}**", inline=True)
    embed.add_field(
        name=f"🏅 Thợ Mỏ Lv.{data['miner_level']}",
        value=f"XP: `{data['miner_xp']}/{data['miner_level'] * 100}` • Lãi ngày: `+{interest_pct:.1f}%`",
        inline=True,
    )
    embed.add_field(
        name="⛏️ Cuốc & Rương",
        value=f"**{pick['name']}** (`{data['durability']}/{pick['max_durability']}`)\n🎁 Rương: **{data['chests']}**",
        inline=True,
    )

    rarity_rank = {r: idx for idx, r in enumerate(reversed(RARITY_ORDER))}
    ore_and_water_rows = []
    mat_rows = []

    for item_name, qty in rows:
        info = ITEMS.get(item_name, {"emoji": "🔹", "unit": "cục", "value": 0, "category": "ore", "rarity": "Common"})
        if info["category"] == "material":
            mat_rows.append((item_name, qty, info))
        else:
            ore_and_water_rows.append((item_name, qty, info))

    ore_and_water_rows.sort(key=lambda x: rarity_rank.get(x[2].get("rarity", "Common"), 99))

    ores_lines = []
    for item_name, qty, info in ore_and_water_rows:
        unit = info["unit"]
        qty_label = f"{qty}{unit}" if unit == "l" else f"{qty} {unit}"
        badge = RARITY_BADGES.get(info.get("rarity", "Common"), "⚪ Common")
        if info["category"] == "water":
            ores_lines.append(f"{info['emoji']} **{item_name}** ×`{qty_label}` • *{badge}* *(Bình Cổ `p fill`)*")
        else:
            ores_lines.append(f"{info['emoji']} **{item_name}** ×`{qty_label}` • *{badge}* *(~{qty * info['value']:,} Vàng)*")

    mat_lines = []
    for item_name, qty, info in mat_rows:
        unit = info["unit"]
        qty_label = f"{qty}{unit}" if unit == "l" else f"{qty} {unit}"
        badge = RARITY_BADGES.get(info.get("rarity", "Common"), "⚪ Common")
        mat_lines.append(f"{info['emoji']} **{item_name}** ×`{qty_label}` • *{badge}*")

    embed.add_field(
        name="⛏️ Quặng & Tài Nguyên (Xếp theo Độ Hiếm)",
        value="\n".join(ores_lines) if ores_lines else "*Trống*",
        inline=False,
    )
    embed.add_field(
        name=f"🏺 Bình Cổ Bệ Đá Giữa Hang: `{data['basin_water']}/120l`",
        value="Dùng `p fill` để tương tác.",
        inline=False,
    )
    embed.add_field(
        name="🧰 Nguyên Liệu Nâng Cấp Cuốc",
        value="\n".join(mat_lines) if mat_lines else "*Trống — mở rương `p chest`*",
        inline=False,
    )

    await ctx.reply(embed=embed)


@bot.command(name="chest", aliases=["ruong", "open"])
async def chest(ctx: commands.Context, amount: str = "1") -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    owned = data["chests"]

    if owned <= 0:
        await ctx.reply("📦 Không còn Rương Kho Báu nào.")
        return

    count = owned if amount.lower() == "all" else (int(amount) if amount.isdigit() else 1)
    if count <= 0 or count > owned:
        await ctx.reply(f"❌ Chỉ có **{owned}** rương.")
        return

    cursor.execute("UPDATE miners SET chests = chests - ? WHERE user_id = ?", (count, uid))
    conn.commit()

    rewards: dict[str, int] = {}
    bonus_gold = 0

    for _ in range(count):
        roll = random.random()
        if roll < 0.55:
            qty = random.randint(1, 3)
            rewards["Đá Mài Thô"] = rewards.get("Đá Mài Thô", 0) + qty
        elif roll < 0.85:
            qty = random.randint(1, 2)
            rewards["Phôi Sắt Gia Cường"] = rewards.get("Phôi Sắt Gia Cường", 0) + qty
        else:
            rewards["Lõi Tinh Thể Cổ"] = rewards.get("Lõi Tinh Thể Cổ", 0) + 1

        if random.random() < 0.20:
            bonus_gold += random.randint(80, 250)

    lines = []
    for mat_name, qty in rewards.items():
        add_item(uid, mat_name, qty)
        info = ITEMS[mat_name]
        badge = RARITY_BADGES.get(info.get("rarity", "Common"), "")
        lines.append(f"{info['emoji']} **{mat_name}**: `+{qty} {info['unit']}` • *{badge}*")

    if bonus_gold > 0:
        add_gold(uid, bonus_gold)
        lines.append(f"💰 **Vàng**: `+{bonus_gold:,}`")

    embed = discord.Embed(
        title=f"🎁 Mở {count} Rương Kho Báu",
        description="\n".join(lines),
        color=discord.Color.orange(),
    )
    await ctx.reply(embed=embed)


@bot.command(name="daily", aliases=["nv", "quest"])
async def daily(ctx: commands.Context) -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    lv = data["miner_level"]
    rate = 0.01 + lv * 0.001

    if data["daily_claimed"] == 0:
        interest_gold = max(50, int(data["gold"] * rate))
        add_gold(uid, interest_gold)
        leveled, lv = add_xp(uid, 25)
        cursor.execute("UPDATE miners SET daily_claimed = 1 WHERE user_id = ?", (uid,))
        conn.commit()
        data = get_miner_row(uid)
        lv_up = f" • 🎉 Lv.{lv}" if leveled else ""
        checkin_line = f"✅ Điểm danh: **+{rate * 100:.1f}%** (Lv.{lv}) = **`+{interest_gold:,} Vàng`**, **`+25 XP`**{lv_up}\n\n"
    else:
        checkin_line = f"☑️ Đã nhận điểm danh hôm nay (**+{rate * 100:.1f}%** • Lv.{lv}).\n\n"

    quests = get_daily_quests(data)
    mask = data["q_claimed_mask"]
    q_lines = []
    claimable_count = 0

    for bit, title, cur, goal, r_gold, r_xp in quests:
        claimed = (mask & bit) != 0
        done = cur >= goal
        if claimed:
            icon, status = "✅", "Đã nhận"
        elif done:
            icon, status = "🎁", "**XONG — `p claim`**"
            claimable_count += 1
        else:
            icon, status = "⬜", f"`{cur}/{goal}`"
        q_lines.append(f"{icon} **{title}** — {status} *(+{r_gold}g, +{r_xp} XP)*")

    reset_ts = next_reset_timestamp()
    embed = discord.Embed(
        title="📅 Daily & Nhiệm Vụ Ngày",
        description=checkin_line + "\n".join(q_lines) + f"\n\n⏰ Reset **07:00 sáng** (<t:{reset_ts}:R>)",
        color=discord.Color.green() if claimable_count else discord.Color.blurple(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=embed)


@bot.command(name="claim", aliases=["nhan"])
async def claim(ctx: commands.Context) -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    quests = get_daily_quests(data)
    mask = data["q_claimed_mask"]

    total_g = 0
    total_x = 0
    claimed_titles = []

    for bit, title, cur, goal, r_gold, r_xp in quests:
        if cur >= goal and (mask & bit) == 0:
            mask |= bit
            total_g += r_gold
            total_x += r_xp
            claimed_titles.append(title)

    if not claimed_titles:
        await ctx.reply("📭 Chưa có nhiệm vụ nào hoàn thành chưa nhận.")
        return

    cursor.execute("UPDATE miners SET q_claimed_mask = ? WHERE user_id = ?", (mask, uid))
    conn.commit()
    add_gold(uid, total_g)
    leveled, new_lv = add_xp(uid, total_x)
    lv_note = f"\n🎉 Thăng cấp **Lv.{new_lv}**" if leveled else ""

    await ctx.reply(
        f"🎉 Nhận thưởng **{len(claimed_titles)} nhiệm vụ**: **`+{total_g:,} Vàng`** & **`+{total_x} XP`**{lv_note}"
    )


@bot.command(name="shop", aliases=["cuahang"])
async def shop(ctx: commands.Context) -> None:
    data = get_miner_row(ctx.author.id)
    pick_lv = data["pickaxe_level"]
    embed = discord.Embed(
        title="🛠️ Cửa Hàng Cuốc Mỏ",
        description=f"Cuốc hiện tại: **Lv.{pick_lv} - {PICKAXES[pick_lv]['name']}** • Dùng `p buy` để nâng cấp.",
        color=discord.Color.teal(),
    )
    for lv, p in PICKAXES.items():
        if lv == 1:
            continue
        status = "✅ Đã có" if lv <= pick_lv else ("🔓 Có thể mua" if lv == pick_lv + 1 else "🔒 Chưa mở")
        req_txt = f"{p['price']:,} Vàng + {p['req_qty']} {p['req_mat']}"
        embed.add_field(
            name=f"Lv.{lv} — {p['name']} (`{req_txt}`) • {status}",
            value=f"{p['desc']}\n*Quặng: {p['bonus_min']}–{p['bonus_max']} • Nước: {p['water_min']}–{p['water_max']}l • Hiếm: x{p['rare_boost']}*",
            inline=False,
        )
    await ctx.reply(embed=embed)


@bot.command(name="buy", aliases=["mua", "upgrade"])
async def buy(ctx: commands.Context) -> None:
    uid = ctx.author.id
    data = get_miner_row(uid)
    next_lv = data["pickaxe_level"] + 1

    if next_lv not in PICKAXES:
        await ctx.reply("🌟 Đã ở cấp cuốc cao nhất.")
        return

    next_pick = PICKAXES[next_lv]
    mat = next_pick["req_mat"]
    req_qty = next_pick["req_qty"]
    have_mat = get_item_qty(uid, mat) if mat else 0

    if data["gold"] < next_pick["price"] or (mat and have_mat < req_qty):
        await ctx.reply(
            f"❌ Chưa đủ: cần **`{next_pick['price']:,}` Vàng** (`{data['gold']:,}`) & **`{req_qty}` {mat}** (`{have_mat}`)."
        )
        return

    add_gold(uid, -next_pick["price"])
    if mat:
        remove_item(uid, mat, req_qty)
    cursor.execute(
        "UPDATE miners SET pickaxe_level = ?, durability = ? WHERE user_id = ?",
        (next_lv, next_pick["max_durability"], uid),
    )
    conn.commit()
    await ctx.reply(f"🎉 Đã nâng cấp lên **{next_pick['name']} (Lv.{next_lv})**.")


@bot.command(name="top", aliases=["lb", "bxh"])
async def top(ctx: commands.Context) -> None:
    cursor.execute("SELECT user_id, gold, miner_level, pickaxe_level FROM miners ORDER BY gold DESC LIMIT 10")
    rows = cursor.fetchall()

    embed = discord.Embed(title="🏆 Top Thợ Mỏ", color=discord.Color.gold())
    if not rows:
        embed.description = "Chưa có dữ liệu."
    else:
        lines = [
            f"**#{i}** <@{uid}> — 💰 **`{gold:,}` Vàng** *(Lv.{mlv} • Cuốc Lv.{plv})*"
            for i, (uid, gold, mlv, plv) in enumerate(rows, 1)
        ]
        embed.description = "\n".join(lines)
    await ctx.reply(embed=embed)


@bot.command(name="help", aliases=["h", "lenh"])
async def help_cmd(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="⛏️ CẨM NANG CHI TIẾT PICKAXECORE",
        description=(
            "Chào mừng thợ mỏ! Dưới đây là tổng quan các hệ thống và lệnh chính (prefix: `p `):\n\n"
            "• **Đào & Kho Đồ (`p mine`, `p bag`, `p chest`, `p top`)**: Khai thác đa tài nguyên theo độ hiếm, mở rương lấy nguyên liệu, theo dõi túi đồ & BXH.\n"
            "• **Bình Cổ & Lò Rèn (`p fill`, `p forge`)**: Hiến tế mạch nước ngầm (`120l`) vào Bình Cổ giữa hang; sửa cuốc hoặc bán từng quặng / bán cả xe quặng.\n"
            "• **Daily & Nâng Cấp (`p daily`, `p claim`, `p shop`, `p buy`)**: Nhận lãi điểm danh theo cấp Thợ Mỏ, làm 5 nhiệm vụ ngày (reset **07:00** sáng) và rèn cuốc mới.\n\n"
            "*Bấm các nút bên dưới để xem hướng dẫn chi tiết từng phần.*"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=embed, view=HelpCategoryView(ctx.author.id))


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Thiếu biến môi trường DISCORD_TOKEN.")
    bot.run(token)


if __name__ == "__main__":
    main()