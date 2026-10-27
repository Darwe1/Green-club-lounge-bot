import random
import json

from vkbottle import Bot, Keyboard, Text
from vkbottle.tools import PhotoMessageUploader

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["vk_token"]
ADMIN_ID = config["admin_id"]

bot = Bot(TOKEN)

BAR_CATEGORIES_PER_PAGE = 8
VALID_GAZEBO_NUMBERS = {"1", "2", "3", "4", "5", "6", "7", "8"}
VOLUME_CANCEL = "❌ Отмена"

TRANSFER_REQUISITES = (
    "Реквизиты для перевода:\n\n"
    "Получатель: Иван Иванов Иванович\n"
    "Банк: ООО «ТЕСТ БАНК»\n"
    "Счёт: xxxx\n"
    "Назначение платежа: Переводы собственных средств"
)

# ======================
# МЕНЮ
# ======================

try:
    with open("menu.json", "r", encoding="utf-8") as f:
        menu = json.load(f)
except FileNotFoundError:
    print("Файл menu.json не найден")
    exit()

kitchen_categories = menu["kitchen_categories"]
bar_categories = menu["bar_categories"]
hookah_menu = menu["hookah_menu"]
extras_menu = menu["extras_menu"]
def build_all_items():
    items = {}
    for category in kitchen_categories.values():
        items.update(category["items"])
    for category in bar_categories.values():
        items.update(category["items"])
    items.update(extras_menu)
    items.update(hookah_menu)
    return items


def build_category_number_maps():
    maps = {}
    for key, category in kitchen_categories.items():
        maps[("kitchen", key)] = {
            str(index): code
            for index, code in enumerate(category["items"], 1)
        }
    for key, category in bar_categories.items():
        maps[("bar", key)] = {
            str(index): code
            for index, code in enumerate(category["items"], 1)
        }
    maps[("hookah", None)] = {
        str(index): code for index, code in enumerate(hookah_menu, 1)
    }
    maps[("extras", None)] = {
        str(index): code for index, code in enumerate(extras_menu, 1)
    }
    return maps


all_items = build_all_items()
CATEGORY_NUMBER_MAPS = build_category_number_maps()

CATEGORY_BY_NAME = {}
for key, category in kitchen_categories.items():
    CATEGORY_BY_NAME[category["name"]] = ("kitchen", key)
for key, category in bar_categories.items():
    CATEGORY_BY_NAME[category["name"]] = ("bar", key)

BAR_CATEGORY_KEYS = list(bar_categories.keys())

HOOKAH_CODES = set(hookah_menu.keys())
BURGER_CODES = {"107", "108", "109"}
SWEET_SOUR_CATEGORIES = {"berry_tea", "lemonade", "drinks"}
SWEET_SOUR_EXCLUDED = {"133", "134", "135"}
CATEGORIES_WITH_MODIFIER_HINT = SWEET_SOUR_CATEGORIES | {"burgers"}

ITEM_TO_KITCHEN_CATEGORY = {}
for category_key, category in kitchen_categories.items():
    for code in category["items"]:
        ITEM_TO_KITCHEN_CATEGORY[code] = category_key

MODIFIER_STEPS = {
    "taste": {
        "key": "taste",
        "prompt": "Выберите вкусовую группу:",
        "type": "select",
        "options": ["Фрукты", "Ягоды", "Цитрусы", "Тропики"],
    },
    "strength": {
        "key": "strength",
        "prompt": "Выберите крепость (от 3 до 8):",
        "type": "select",
        "options": ["3", "4", "5", "6", "7", "8"],
        "buttons_per_row": 3,
    },
    "wishes": {
        "key": "wishes",
        "prompt": (
            "Напишите свои пожелания к кальяну.\n\n"
            "Если пожеланий нет — напишите «нет»."
        ),
        "type": "text",
    },
    "spicy": {
        "key": "spicy",
        "prompt": "Острый или не острый?",
        "type": "select",
        "options": ["Острый", "Не острый"],
    },
    "sweet_sour": {
        "key": "sweet_sour",
        "prompt": "Сделать напиток:",
        "type": "select",
        "options": ["По слаще", "По кислее"],
    },
}

# ======================
# ПАМЯТЬ
# ======================

user_data = {}


def new_user_state():
    return {
        "cart": [],
        "comment": "",
        "payment": "",
        "gazebo": "",
        "payment_attachment": None,
        "state": None,
        "order_sent": False,
        "menu_section": None,
        "category_key": None,
        "bar_page": 0,
        "pending_item": None,
        "volume_option_map": {},
        "selection_kind": None,
        "pending_cart_data": None,
        "modifier_queue": [],
        "modifier_values": {},
        "modifier_step": None,
    }


def get_user(uid):
    if uid not in user_data:
        user_data[uid] = new_user_state()
    return user_data[uid]


def is_range_price(price):
    return isinstance(price, str) and "/" in price


def parse_range_prices(price):
    return [int(part.strip()) for part in price.split("/")]


def has_variants(item):
    return bool(item.get("variants"))


def needs_option_selection(item):
    return is_range_price(item["price"]) or has_variants(item)


def get_variant_options(item):
    return [
        {"label": variant, "price": item["price"]}
        for variant in item["variants"]
    ]


def get_volume_options(item):
    prices = parse_range_prices(item["price"])
    labels = item.get("volumes")
    if labels and len(labels) == len(prices):
        return [
            {"label": label, "price": price}
            for label, price in zip(labels, prices)
        ]
    return [{"label": f"{price}₽", "price": price} for price in prices]


def volume_button_text(option):
    label = option["label"]
    price = option["price"]
    if label.endswith("₽"):
        return label
    return f"{label} — {price}₽"


def selection_button_text(option, kind):
    if kind == "variant":
        return option["label"]
    return volume_button_text(option)


def get_selection_kb(options, kind):
    kb = Keyboard(one_time=True)
    for index, option in enumerate(options):
        if index % 2 == 0 and index > 0:
            kb.row()
        kb.add(Text(selection_button_text(option, kind)))
        if index % 2 == 1 or index == len(options) - 1:
            kb.row()
    kb.add(Text(VOLUME_CANCEL))
    return kb


def format_price(price):
    if is_range_price(price):
        return f"{price}₽"
    return f"{price}₽"


def format_line_amount(price, count):
    return f"{price * count}₽"


def format_cart_total(cart):
    return f"{sum(item['price'] for item in cart)}₽"


def format_volumes_for_menu(item):
    if has_variants(item):
        variants = ", ".join(item["variants"])
        return f"Варианты: {variants} — {format_price(item['price'])}"
    if is_range_price(item["price"]):
        options = get_volume_options(item)
        parts = [f"{option['label']} — {option['price']}₽" for option in options]
        return f"Объёмы: {' / '.join(parts)}"
    volume = item.get("volume")
    if volume and not isinstance(volume, list):
        return f"Объём: {volume} — {format_price(item['price'])}"
    return f"Цена: {format_price(item['price'])}"


def resolve_item_code(user, text):
    section = user.get("menu_section")
    category_key = user.get("category_key")

    if section == "kitchen_category":
        return CATEGORY_NUMBER_MAPS.get(("kitchen", category_key), {}).get(text)
    if section == "bar_category":
        return CATEGORY_NUMBER_MAPS.get(("bar", category_key), {}).get(text)
    if section == "hookah":
        return CATEGORY_NUMBER_MAPS.get(("hookah", None), {}).get(text)
    if section == "extras":
        return CATEGORY_NUMBER_MAPS.get(("extras", None), {}).get(text)
    return None


def format_menu_item(code, item, display_number=None):
    number = display_number if display_number is not None else code
    text = f"{number}. {item['name']}\n"
    if item.get("composition"):
        text += f"   Состав: {item['composition']}\n"
    text += f"   {format_volumes_for_menu(item)}\n"
    return text


def get_modifier_steps(item_code):
    if item_code in HOOKAH_CODES:
        return ["taste", "strength", "wishes"]
    if item_code in BURGER_CODES:
        return ["spicy"]
    category = ITEM_TO_KITCHEN_CATEGORY.get(item_code)
    if category in SWEET_SOUR_CATEGORIES and item_code not in SWEET_SOUR_EXCLUDED:
        return ["sweet_sour"]
    return []


def get_modifier_kb(step_key):
    step = MODIFIER_STEPS[step_key]
    options = step["options"]
    per_row = step.get("buttons_per_row", 2)
    kb = Keyboard(one_time=True)
    for index, option in enumerate(options):
        if index % per_row == 0 and index > 0:
            kb.row()
        kb.add(Text(option))
        if (index + 1) % per_row == 0 or index == len(options) - 1:
            kb.row()
    kb.add(Text(VOLUME_CANCEL))
    return kb


def get_order_line_name(item):
    name = item["name"]
    variant = item.get("variant")
    volume = item.get("volume")
    if variant:
        name = f"{name} — {variant}"
    elif volume:
        name = f"{name} — {volume}"

    mods = item.get("modifiers", {})
    mod_parts = []
    if mods.get("taste"):
        mod_parts.append(mods["taste"])
    if mods.get("strength"):
        mod_parts.append(f"крепость {mods['strength']}")
    if mods.get("wishes"):
        mod_parts.append(f"пожелания: {mods['wishes']}")
    if mods.get("spicy"):
        mod_parts.append(mods["spicy"].lower())
    if mods.get("sweet_sour"):
        mod_parts.append(mods["sweet_sour"].lower())

    if mod_parts:
        name = f"{name} — {', '.join(mod_parts)}"
    return name


def cart_item_from_menu(
    item, volume=None, variant=None, price=None, modifiers=None
):
    cart_item = {
        "name": item["name"],
        "price": price if price is not None else item["price"],
    }
    if item.get("composition"):
        cart_item["composition"] = item["composition"]
    if variant is not None:
        cart_item["variant"] = variant
    else:
        selected_volume = volume if volume is not None else item.get("volume")
        if selected_volume and not isinstance(selected_volume, list):
            cart_item["volume"] = selected_volume
    if modifiers:
        filtered = {key: value for key, value in modifiers.items() if value}
        if filtered:
            cart_item["modifiers"] = filtered
    return cart_item


def format_selection_prompt(item, kind):
    if kind == "variant":
        text = f"Выберите вариант для:\n{item['name']}"
    else:
        text = f"Выберите объём для:\n{item['name']}"
    if item.get("composition"):
        text += f"\nСостав: {item['composition']}"
    return text


def cancel_pending_order(user):
    user["state"] = None
    user["pending_item"] = None
    user["volume_option_map"] = {}
    user["selection_kind"] = None
    user["pending_cart_data"] = None
    user["modifier_queue"] = []
    user["modifier_values"] = {}
    user["modifier_step"] = None


def start_modifier_flow(user, item_code):
    steps = get_modifier_steps(item_code)
    if not steps:
        return False
    user["modifier_queue"] = steps[1:]
    user["modifier_values"] = {}
    user["modifier_step"] = steps[0]
    return True


async def prompt_modifier_step(message, user):
    step_key = user["modifier_step"]
    step = MODIFIER_STEPS[step_key]
    if step["type"] == "select":
        user["state"] = "modifier_select"
        await message.answer(
            step["prompt"],
            keyboard=get_modifier_kb(step_key).get_json(),
        )
    else:
        user["state"] = "modifier_text"
        await message.answer(step["prompt"])


async def finalize_pending_item(message, user):
    data = user["pending_cart_data"]
    item = all_items[data["code"]]
    cart_entry = cart_item_from_menu(
        item,
        volume=data.get("volume"),
        variant=data.get("variant"),
        price=data.get("price"),
        modifiers=user.get("modifier_values"),
    )
    user["cart"].append(cart_entry)
    line_name = get_order_line_name(cart_entry)
    price = cart_entry["price"]
    cancel_pending_order(user)
    await message.answer(
        f"✅ Добавлено:\n{line_name}\n{price}₽",
        keyboard=main_kb.get_json(),
    )


def format_category_items(category, category_key=None):
    text = f"{category['name']}\n\n"
    if category["items"]:
        for index, (code, item) in enumerate(category["items"].items(), 1):
            text += format_menu_item(code, item, display_number=index)
    else:
        text += "Позиции пока не добавлены.\n"
    text += (
        "\nДля добавления товара отправьте его номер."
        "\nЕсли у позиции несколько объёмов или вариантов — "
        "после ввода номера выберите нужный."
    )
    if category_key in CATEGORIES_WITH_MODIFIER_HINT:
        text += "\nПосле выбора номера уточним настройки."
    return text


def get_kitchen_kb():
    kb = Keyboard(one_time=False)
    keys = list(kitchen_categories.keys())
    for index, key in enumerate(keys):
        if index % 2 == 0 and index > 0:
            kb.row()
        kb.add(Text(kitchen_categories[key]["name"]))
        if index % 2 == 1 or index == len(keys) - 1:
            kb.row()
    kb.add(Text("🏠 Главное меню"))
    return kb


def get_bar_kb(page=0):
    total_pages = (
        len(BAR_CATEGORY_KEYS) + BAR_CATEGORIES_PER_PAGE - 1
    ) // BAR_CATEGORIES_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start = page * BAR_CATEGORIES_PER_PAGE
    page_keys = BAR_CATEGORY_KEYS[start : start + BAR_CATEGORIES_PER_PAGE]

    kb = Keyboard(one_time=False)
    for index, key in enumerate(page_keys):
        if index % 2 == 0 and index > 0:
            kb.row()
        kb.add(Text(bar_categories[key]["name"]))
        if index % 2 == 1 or index == len(page_keys) - 1:
            kb.row()

    if page > 0:
        kb.add(Text("⬅️ Назад"))
    if page < total_pages - 1:
        if page > 0:
            kb.add(Text("➡️ Ещё"))
        else:
            kb.add(Text("➡️ Ещё"))
    if page > 0 or page < total_pages - 1:
        kb.row()
    kb.add(Text("🏠 Главное меню"))
    return kb


def count_cart_items(cart):
    items_count = {}
    for item in cart:
        line_name = get_order_line_name(item)
        if line_name not in items_count:
            items_count[line_name] = {"count": 0, "price": item["price"]}
        items_count[line_name]["count"] += 1
    return items_count


def build_order_text(uid, user):
    items_count = count_cart_items(user["cart"])
    order_text = (
        "📦 НОВЫЙ ЗАКАЗ\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👤 VK ID: {uid}\n"
        f"🏕 Беседка: {user['gazebo']}\n\n"
        "🛒 Состав заказа:\n"
    )
    for name, data in items_count.items():
        order_text += (
            f"• {name} ×{data['count']} "
            f"— {format_line_amount(data['price'], data['count'])}\n"
        )
    order_text += (
        f"\n💰 Итого: {format_cart_total(user['cart'])}\n"
        f"💬 Комментарий: {user['comment']}\n"
        f"💳 Оплата: {user['payment']}"
    )
    return order_text


def get_largest_photo_url(photo):
    if photo.photo_256:
        return photo.photo_256
    if photo.images:
        best = max(
            photo.images,
            key=lambda image: (image.width or 0) * (image.height or 0),
        )
        return best.url
    if photo.sizes:
        best = max(
            photo.sizes,
            key=lambda size: (size.width or 0) * (size.height or 0),
        )
        return best.url
    return None


async def reupload_photo_for_admin(photo):
    url = get_largest_photo_url(photo)
    if not url:
        raise ValueError("Photo URL not found")

    image_bytes = await bot.api.http_client.request_content(url)
    uploader = PhotoMessageUploader(bot.api)
    return await uploader.upload(image_bytes, peer_id=ADMIN_ID)


async def send_order_to_admin(uid):
    user = get_user(uid)
    order_text = build_order_text(uid, user)
    send_kwargs = {
        "peer_id": ADMIN_ID,
        "message": order_text,
        "random_id": random.randint(1, 2147483647),
    }
    if user.get("payment_attachment"):
        send_kwargs["attachment"] = user["payment_attachment"]
    await bot.api.messages.send(**send_kwargs)
    user["order_sent"] = True


# ======================
# КЛАВИАТУРЫ
# ======================

main_kb = (
    Keyboard(one_time=False)
    .add(Text("🍽 Меню кухни"))
    .add(Text("🍹 Меню бара"))
    .row()
    .add(Text("💨 Меню кальяна"))
    .add(Text("➕ Дополнительно"))
    .row()
    .add(Text("🛒 Корзина"))
    .add(Text("🗑 Очистить корзину"))
)

payment_kb = (
    Keyboard(one_time=True)
    .add(Text("💳 По карте"))
    .row()
    .add(Text("💵 Наличными"))
    .row()
    .add(Text("📱 Переводом"))
)

cart_kb = (
    Keyboard(one_time=False)
    .add(Text("✅ Оформить заказ"))
    .row()
    .add(Text("➖ Удалить последний"))
    .row()
    .add(Text("🗑 Очистить корзину"))
    .row()
    .add(Text("⬅️ Назад"))
)

category_back_kb = (
    Keyboard(one_time=False)
    .add(Text("⬅️ Назад"))
    .row()
    .add(Text("🏠 Главное меню"))
)

# ======================
# СТАРТ
# ======================


@bot.on.message(text=["Начать", "начать", "Старт", "старт"])
async def start(message):
    get_user(message.from_id)
    await message.answer(
        "Добро пожаловать в ресторан Green Club\n\n"
        "Выберите раздел:",
        keyboard=main_kb.get_json(),
    )


# ======================
# НАВИГАЦИЯ
# ======================


@bot.on.message(text="🏠 Главное меню")
async def main_menu(message):
    user = get_user(message.from_id)
    cancel_pending_order(user)
    user["menu_section"] = None
    user["category_key"] = None
    user["bar_page"] = 0
    await message.answer(
        "Главное меню:",
        keyboard=main_kb.get_json(),
    )


@bot.on.message(text="⬅️ Назад")
async def back(message):
    uid = message.from_id
    user = get_user(uid)
    cancel_pending_order(user)

    if user.get("menu_section") == "kitchen_category":
        user["menu_section"] = "kitchen"
        user["category_key"] = None
        await message.answer(
            "🍽 МЕНЮ КУХНИ\n\nВыберите категорию:",
            keyboard=get_kitchen_kb().get_json(),
        )
        return

    if user.get("menu_section") == "bar_category":
        user["menu_section"] = "bar"
        user["category_key"] = None
        await message.answer(
            "🍹 МЕНЮ БАРА\n\nВыберите категорию:",
            keyboard=get_bar_kb(user.get("bar_page", 0)).get_json(),
        )
        return

    if user.get("menu_section") == "bar" and user.get("bar_page", 0) > 0:
        user["bar_page"] -= 1
        await message.answer(
            "🍹 МЕНЮ БАРА\n\nВыберите категорию:",
            keyboard=get_bar_kb(user["bar_page"]).get_json(),
        )
        return

    user["menu_section"] = None
    user["category_key"] = None
    user["bar_page"] = 0
    await message.answer(
        "Главное меню:",
        keyboard=main_kb.get_json(),
    )


@bot.on.message(text="➡️ Ещё")
async def bar_next_page(message):
    user = get_user(message.from_id)
    cancel_pending_order(user)
    if user.get("menu_section") != "bar":
        return

    total_pages = (
        len(BAR_CATEGORY_KEYS) + BAR_CATEGORIES_PER_PAGE - 1
    ) // BAR_CATEGORIES_PER_PAGE
    if user.get("bar_page", 0) >= total_pages - 1:
        return

    user["bar_page"] += 1
    await message.answer(
        "🍹 МЕНЮ БАРА\n\nВыберите категорию:",
        keyboard=get_bar_kb(user["bar_page"]).get_json(),
    )


# ======================
# МЕНЮ КУХНИ
# ======================


@bot.on.message(text="🍽 Меню кухни")
async def kitchen(message):
    user = get_user(message.from_id)
    cancel_pending_order(user)
    user["menu_section"] = "kitchen"
    user["category_key"] = None
    user["bar_page"] = 0
    await message.answer(
        "🍽 МЕНЮ КУХНИ\n\nВыберите категорию:",
        keyboard=get_kitchen_kb().get_json(),
    )


# ======================
# МЕНЮ БАРА
# ======================


@bot.on.message(text="🍹 Меню бара")
async def bar(message):
    user = get_user(message.from_id)
    cancel_pending_order(user)
    user["menu_section"] = "bar"
    user["category_key"] = None
    user["bar_page"] = 0
    await message.answer(
        "🍹 МЕНЮ БАРА\n\nВыберите категорию:",
        keyboard=get_bar_kb(0).get_json(),
    )


# ======================
# МЕНЮ КАЛЬЯНА
# ======================


@bot.on.message(text="💨 Меню кальяна")
async def hookah(message):
    user = get_user(message.from_id)
    cancel_pending_order(user)
    user["menu_section"] = "hookah"
    user["category_key"] = None
    user["bar_page"] = 0

    text = "💨 МЕНЮ КАЛЬЯНА\n\n"
    for index, (code, item) in enumerate(hookah_menu.items(), 1):
        text += format_menu_item(code, item, display_number=index)
    text += (
        "\nДля добавления товара отправьте его номер."
        "\nПосле выбора номера уточним вкус, крепость и пожелания."
    )

    await message.answer(
        text,
        keyboard=main_kb.get_json(),
    )


# ======================
# ДОПОЛНИТЕЛЬНО
# ======================


@bot.on.message(text="➕ Дополнительно")
async def extras(message):
    user = get_user(message.from_id)
    cancel_pending_order(user)
    user["menu_section"] = "extras"
    user["category_key"] = None
    user["bar_page"] = 0

    text = "➕ ДОПОЛНИТЕЛЬНО\n\n"
    if extras_menu:
        for index, (code, item) in enumerate(extras_menu.items(), 1):
            text += format_menu_item(code, item, display_number=index)
    else:
        text += "Позиции пока не добавлены.\n"
    text += "\nДля добавления товара отправьте его номер."

    await message.answer(
        text,
        keyboard=main_kb.get_json(),
    )


# ======================
# ОЧИСТКА КОРЗИНЫ
# ======================


@bot.on.message(text="🗑 Очистить корзину")
async def clear_cart(message):
    user_data[message.from_id] = new_user_state()
    await message.answer(
        "🗑 Корзина очищена.",
        keyboard=main_kb.get_json(),
    )


# ======================
# КОРЗИНА
# ======================


@bot.on.message(text="🛒 Корзина")
async def cart(message):
    uid = message.from_id
    user = get_user(uid)

    if not user["cart"]:
        await message.answer(
            "Корзина пуста.",
            keyboard=main_kb.get_json(),
        )
        return

    text = "🛒 Ваш заказ\n\n"
    items_count = count_cart_items(user["cart"])

    for name, data in items_count.items():
        text += (
            f"• {name} ×{data['count']} "
            f"— {format_line_amount(data['price'], data['count'])}\n"
        )

    text += f"\n💰 Итого: {format_cart_total(user['cart'])}"

    await message.answer(
        text,
        keyboard=cart_kb.get_json(),
    )


# ======================
# УДАЛЕНИЕ ПОСЛЕДНЕГО
# ======================


@bot.on.message(text="➖ Удалить последний")
async def remove_last(message):
    uid = message.from_id
    user = get_user(uid)

    if not user["cart"]:
        await message.answer("Корзина пуста.")
        return

    deleted = user["cart"].pop()
    await message.answer(f"Удалено: {get_order_line_name(deleted)}")


# ======================
# ДОБАВЛЕНИЕ ТОВАРОВ И ОФОРМЛЕНИЕ
# ======================


@bot.on.message()
async def add_product(message):
    uid = message.from_id
    user = get_user(uid)
    text = message.text or ""

    # ======================
    # СКРИНШОТ ОПЛАТЫ
    # ======================

    if user["state"] == "payment_screenshot":
        photos = message.get_photo_attachments()
        if not photos:
            await message.answer(
                "Пожалуйста, отправьте фото (скриншот оплаты)."
            )
            return

        try:
            user["payment_attachment"] = await reupload_photo_for_admin(
                photos[0]
            )
        except Exception:
            await message.answer(
                "Не удалось обработать фото. "
                "Попробуйте отправить скриншот ещё раз."
            )
            return

        await send_order_to_admin(uid)
        await message.answer(
            "✅ Заказ успешно отправлен!\n\n"
            "Официант скоро обработает ваш заказ.\n"
            "Спасибо, что выбрали Green Lounge 🍀",
            keyboard=main_kb.get_json(),
        )
        user_data[uid] = new_user_state()
        return

    # ======================
    # ОФОРМЛЕНИЕ ЗАКАЗА
    # ======================

    if text == "✅ Оформить заказ":
        if not user["cart"]:
            await message.answer("Корзина пуста.")
            return

        if user["order_sent"]:
            await message.answer("Ваш заказ уже отправлен.")
            return

        user["state"] = "gazebo"
        await message.answer(
            "Укажите номер вашей беседки (от 1 до 8):"
        )
        return

    # ======================
    # НОМЕР БЕСЕДКИ
    # ======================

    if user["state"] == "gazebo":
        if text not in VALID_GAZEBO_NUMBERS:
            await message.answer(
                "Некорректный номер. Укажите номер беседки от 1 до 8."
            )
            return

        user["gazebo"] = text
        user["state"] = "comment"
        await message.answer(
            "Введите комментарий к заказу.\n\n"
            "Если пожеланий нет — напишите 'нет'."
        )
        return

    # ======================
    # КОММЕНТАРИЙ
    # ======================

    if user["state"] == "comment":
        user["comment"] = text
        user["state"] = "payment"
        await message.answer(
            "Выберите способ оплаты:",
            keyboard=payment_kb.get_json(),
        )
        return

    # ======================
    # ОПЛАТА
    # ======================

    if user["state"] == "payment" and text in [
        "💳 По карте",
        "💵 Наличными",
        "📱 Переводом",
    ]:
        user["payment"] = text

        if text == "💳 По карте":
            await message.answer(
                "К вам подойдет сотрудник для оплаты картой."
            )
        elif text == "💵 Наличными":
            await message.answer(
                "К вам подойдет сотрудник для приема наличных."
            )
        else:
            user["state"] = "payment_screenshot"
            total = format_cart_total(user["cart"])
            await message.answer(
                f"{TRANSFER_REQUISITES}\n\n"
                f"💰 Сумма к оплате: {total}\n\n"
                "Переведите указанную сумму по реквизитам выше.\n"
                "После оплаты отправьте скриншот перевода (фото)."
            )
            return

        await send_order_to_admin(uid)
        await message.answer(
            "✅ Заказ успешно отправлен!\n\n"
            "Официант скоро обработает ваш заказ.\n"
            "Спасибо, что выбрали Green Club",
            keyboard=main_kb.get_json(),
        )
        user_data[uid] = new_user_state()
        return

    # ======================
    # ВЫБОР ОБЪЁМА
    # ======================

    if user["state"] == "volume_select":
        kind = user.get("selection_kind", "volume")
        if text == VOLUME_CANCEL:
            cancel_pending_order(user)
            cancel_text = (
                "Выбор варианта отменён."
                if kind == "variant"
                else "Выбор объёма отменён."
            )
            await message.answer(
                cancel_text,
                keyboard=main_kb.get_json(),
            )
            return

        option = user.get("volume_option_map", {}).get(text)
        if not option:
            retry_text = (
                "Выберите вариант из предложенных "
                "или нажмите «Отмена»."
                if kind == "variant"
                else "Выберите объём из предложенных вариантов "
                "или нажмите «Отмена»."
            )
            await message.answer(retry_text)
            return

        item_code = user["pending_item"]
        user["pending_cart_data"] = {
            "code": item_code,
            "volume": option["label"] if kind != "variant" else None,
            "variant": option["label"] if kind == "variant" else None,
            "price": option["price"],
        }
        user["state"] = None
        user["pending_item"] = None
        user["volume_option_map"] = {}
        user["selection_kind"] = None

        if start_modifier_flow(user, item_code):
            await prompt_modifier_step(message, user)
        else:
            await finalize_pending_item(message, user)
        return

    # ======================
    # ВЫБОР МОДИФИКАТОРОВ
    # ======================

    if user["state"] == "modifier_select":
        if text == VOLUME_CANCEL:
            cancel_pending_order(user)
            await message.answer(
                "Выбор отменён.",
                keyboard=main_kb.get_json(),
            )
            return

        step_key = user["modifier_step"]
        step = MODIFIER_STEPS[step_key]
        if text not in step["options"]:
            await message.answer(
                "Выберите вариант из предложенных или нажмите «Отмена»."
            )
            return

        user["modifier_values"][step["key"]] = text
        if user["modifier_queue"]:
            user["modifier_step"] = user["modifier_queue"].pop(0)
            await prompt_modifier_step(message, user)
        else:
            await finalize_pending_item(message, user)
        return

    if user["state"] == "modifier_text":
        wishes = "" if text.strip().lower() == "нет" else text.strip()
        user["modifier_values"]["wishes"] = wishes
        await finalize_pending_item(message, user)
        return

    # ======================
    # ВЫБОР КАТЕГОРИИ МЕНЮ
    # ======================

    if text in CATEGORY_BY_NAME:
        cancel_pending_order(user)
        section, category_key = CATEGORY_BY_NAME[text]
        if section == "kitchen":
            category = kitchen_categories[category_key]
            user["menu_section"] = "kitchen_category"
        else:
            category = bar_categories[category_key]
            user["menu_section"] = "bar_category"
        user["category_key"] = category_key

        await message.answer(
            format_category_items(category, category_key),
            keyboard=category_back_kb.get_json(),
        )
        return

    # ======================
    # ДОБАВЛЕНИЕ ТОВАРОВ
    # ======================

    if user["state"] is not None:
        return

    item_code = resolve_item_code(user, text)
    if item_code and item_code in all_items:
        item = all_items[item_code]

        if needs_option_selection(item):
            if has_variants(item):
                options = get_variant_options(item)
                kind = "variant"
            else:
                options = get_volume_options(item)
                kind = "volume"
            user["state"] = "volume_select"
            user["pending_item"] = item_code
            user["selection_kind"] = kind
            user["volume_option_map"] = {
                selection_button_text(option, kind): option
                for option in options
            }
            await message.answer(
                format_selection_prompt(item, kind),
                keyboard=get_selection_kb(options, kind).get_json(),
            )
            return

        user["pending_cart_data"] = {
            "code": item_code,
            "volume": None,
            "variant": None,
            "price": None,
        }
        if start_modifier_flow(user, item_code):
            await prompt_modifier_step(message, user)
            return

        user["pending_cart_data"] = None
        user["cart"].append(cart_item_from_menu(item))
        line_name = get_order_line_name(user["cart"][-1])
        await message.answer(
            f"✅ Добавлено:\n{line_name}\n{format_price(item['price'])}"
        )
        return


# ======================
# ЗАПУСК
# ======================

bot.run()
