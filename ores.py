from pathlib import Path

ASSETS_DIR = Path("assets")

# category: "ore" (bán cho chủ lò rèn), "water" (nạp bình cổ), "material" (nguyên liệu sửa/nâng cuốc)
ITEMS = {
    "Đá Vụn": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Common",
        "weight": 38,
        "value": 5,
        "emoji": "🪨",
        "icon_file": "stone.png",
    },
    "Mạch Nước Ngầm": {
        "category": "water",
        "unit": "l",
        "rarity": "Common",
        "weight": 24,
        "value": 0,  # Không bán được, dùng nạp bình cổ 120l
        "emoji": "💧",
        "icon_file": "water_vein.png",
    },
    "Quặng Đồng": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Uncommon",
        "weight": 18,
        "value": 18,
        "emoji": "🥉",
        "icon_file": "copper.png",
    },
    "Quặng Sắt": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Rare",
        "weight": 10,
        "value": 40,
        "emoji": "⛓️",
        "icon_file": "iron.png",
    },
    "Dầu Mỏ": {
        "category": "ore",
        "unit": "l",
        "rarity": "Rare",
        "weight": 5,
        "value": 75,
        "emoji": "🛢️",
        "icon_file": "oil.png",
    },
    "Quặng Vàng": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Epic",
        "weight": 3,
        "value": 120,
        "emoji": "🥇",
        "icon_file": "gold.png",
    },
    "Obsidian": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Epic",
        "weight": 1.5,
        "value": 160,
        "emoji": "🖤",
        "icon_file": "obsidian.png",
    },
    "Tinh Thể Lục Bảo": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Legendary",
        "weight": 0.8,
        "value": 280,
        "emoji": "💚",
        "icon_file": "emerald.png",
    },
    "Kim Cương": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Legendary",
        "weight": 0.5,
        "value": 450,
        "emoji": "💎",
        "icon_file": "diamond.png",
    },
    "Thiên Thạch Tinh Thể": {
        "category": "ore",
        "unit": "cục",
        "rarity": "Mythic",
        "weight": 0.2,
        "value": 900,
        "emoji": "🌌",
        "icon_file": "meteor.png",
    },
    # --- NGUYÊN LIỆU TỪ RƯƠNG (SỬA CHỮA & NÂNG CẤP CUỐC) ---
    "Đá Mài Thô": {
        "category": "material",
        "unit": "viên",
        "rarity": "Common",
        "weight": 0,
        "value": 0,
        "emoji": "🧱",
        "icon_file": "whetstone.png",
    },
    "Phôi Sắt Gia Cường": {
        "category": "material",
        "unit": "thanh",
        "rarity": "Rare",
        "weight": 0,
        "value": 0,
        "emoji": "🔩",
        "icon_file": "iron_ingot.png",
    },
    "Lõi Tinh Thể Cổ": {
        "category": "material",
        "unit": "mảnh",
        "rarity": "Epic",
        "weight": 0,
        "value": 0,
        "emoji": "💠",
        "icon_file": "crystal_core.png",
    },
}

PICKAXES = {
    1: {
        "name": "Cuốc Gỗ Cũ Kỹ",
        "price": 0,
        "req_mat": None,
        "req_qty": 0,
        "max_durability": 30,
        "repair_mat": "Đá Mài Thô",
        "repair_qty": 1,
        "bonus_min": 1,
        "bonus_max": 2,
        "water_min": 3,
        "water_max": 6,
        "rare_boost": 1.0,
        "desc": "Cuốc khởi đầu, độ bền 30.",
    },
    2: {
        "name": "Cuốc Sắt Rèn Tay",
        "price": 300,
        "req_mat": "Đá Mài Thô",
        "req_qty": 3,
        "max_durability": 55,
        "repair_mat": "Đá Mài Thô",
        "repair_qty": 2,
        "bonus_min": 1,
        "bonus_max": 3,
        "water_min": 5,
        "water_max": 10,
        "rare_boost": 1.35,
        "desc": "Độ bền 55, tăng nhẹ tỷ lệ quặng hiếm & lượng nước ngầm.",
    },
    3: {
        "name": "Cuốc Pha Lê Cộng Hưởng",
        "price": 1000,
        "req_mat": "Phôi Sắt Gia Cường",
        "req_qty": 3,
        "max_durability": 90,
        "repair_mat": "Phôi Sắt Gia Cường",
        "repair_qty": 1,
        "bonus_min": 2,
        "bonus_max": 4,
        "water_min": 8,
        "water_max": 15,
        "rare_boost": 1.8,
        "desc": "Độ bền 90, đào nhiều quặng và mạch nước dồi dào hơn.",
    },
    4: {
        "name": "Cuốc Lõi Hư Không",
        "price": 2800,
        "req_mat": "Lõi Tinh Thể Cổ",
        "req_qty": 2,
        "max_durability": 150,
        "repair_mat": "Phôi Sắt Gia Cường",
        "repair_qty": 2,
        "bonus_min": 2,
        "bonus_max": 5,
        "water_min": 12,
        "water_max": 22,
        "rare_boost": 2.5,
        "desc": "Độ bền 150, chuyên săn Kim Cương và Thiên Thạch.",
    },
}


def get_adjusted_weights(pickaxe_level: int) -> tuple[list[str], list[float]]:
    rare_tiers = {"Rare", "Epic", "Legendary", "Mythic"}
    boost = PICKAXES.get(pickaxe_level, PICKAXES[1])["rare_boost"]

    names: list[str] = []
    weights: list[float] = []
    for item_name, info in ITEMS.items():
        if info["weight"] <= 0:
            continue
        w = float(info["weight"])
        if info["rarity"] in rare_tiers:
            w *= boost
        names.append(item_name)
        weights.append(w)
    return names, weights


def get_item_icon_path(item_name: str) -> Path | None:
    info = ITEMS.get(item_name)
    if not info:
        return None
    icon_file = info.get("icon_file")
    if not icon_file:
        return None
    path = ASSETS_DIR / icon_file
    return path if path.exists() else None