import logging
import os
import sqlite3
import unicodedata
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Render gives PORT automatically for Web Services.
PORT = int(os.getenv("PORT", "10000"))

# Render automatically provides these for Web Services.
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")

# =========================================================
# DATABASE
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "bot.db")

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================================================
# MAIN BUTTONS
# =========================================================

BTN_SERVICES = "🔧 Хизматлар"
BTN_WORKER = "👨‍🔧 Уста чақириш"
BTN_ANNOUNCEMENT = "📢 Эълон бериш"
BTN_CONTACT = "Алоқа"
BTN_BACK = "⬅️ Орқага"

BTN_REGISTER_WORKER = "👨‍🔧 Уста бўлиб рўйхатдан ўтиш"
BTN_MY_PROFILE = "👤 Менинг профилим"

# =========================================================
# SERVICES
# =========================================================

SERVICES = [
    "🔧 Сантехник",
    "⚡ Электрик",
    "📱 Телефон таъмири",
    "💻 Компьютер таъмири",
    "🧹 Уй тозалаш",
    "🪑 Мебель таъмири",
]

# =========================================================
# STATES
# =========================================================

CUSTOMER_NAME = 0
CUSTOMER_PHONE = 1
CUSTOMER_ADDRESS = 2
CUSTOMER_PROBLEM = 3

WORKER_NAME = 10
WORKER_PHONE = 11
WORKER_SERVICE = 12
WORKER_AREA = 13
WORKER_PRICE = 14

ANNOUNCEMENT_NAME = 20
ANNOUNCEMENT_PHONE = 21
ANNOUNCEMENT_SERVICE = 22
ANNOUNCEMENT_ADDRESS = 23
ANNOUNCEMENT_BUDGET = 24
ANNOUNCEMENT_DETAILS = 25

PROFILE_NAME = 30
PROFILE_PHONE = 31
PROFILE_SERVICE = 32
PROFILE_AREA = 33
PROFILE_PRICE = 34


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            area TEXT NOT NULL,
            price TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            address TEXT NOT NULL,
            problem TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            accepted_worker_id INTEGER,
            accepted_worker_name TEXT,
            created_at TEXT NOT NULL,
            accepted_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            address TEXT NOT NULL,
            budget TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()

    # Check orders columns
    columns = {
        row["name"]
        for row in cur.execute(
            "PRAGMA table_info(orders)"
        ).fetchall()
    }

    if "status" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN "
            "status TEXT NOT NULL DEFAULT 'pending'"
        )

    if "accepted_worker_id" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN "
            "accepted_worker_id INTEGER"
        )

    if "accepted_worker_name" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN "
            "accepted_worker_name TEXT"
        )

    if "accepted_at" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN "
            "accepted_at TEXT"
        )

    conn.commit()
    conn.close()


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_text(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.casefold().strip()

    replacements = {
        "ё": "е",
        "ў": "у",
        "қ": "к",
        "ғ": "г",
        "ҳ": "х",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return " ".join(text.split())


def normalize_service_name(text):
    text = normalize_text(text)

    for emoji in [
        "🔧",
        "⚡",
        "📱",
        "💻",
        "🧹",
        "🪑"
    ]:
        text = text.replace(emoji, "")

    text = text.strip()

    aliases = {
        "сантехник": "santehnik",
        "santehnik": "santehnik",
        "сантехника": "santehnik",

        "электрик": "elektrik",
        "elektrik": "elektrik",

        "телефон таъмири": "telefon tamiri",
        "telefon tamiri": "telefon tamiri",

        "компьютер таъмири": "kompyuter tamiri",
        "kompyuter tamiri": "kompyuter tamiri",

        "уй тозалаш": "uy tozalash",
        "uy tozalash": "uy tozalash",

        "мебель таъмири": "mebel tamiri",
        "mebel tamiri": "mebel tamiri",
    }

    return aliases.get(text, text)


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_SERVICES],
            [BTN_WORKER],
            [BTN_ANNOUNCEMENT],
            [BTN_CONTACT],
        ],
        resize_keyboard=True,
    )


def services_keyboard():
    return ReplyKeyboardMarkup(
        [
            [SERVICES[0], SERVICES[1]],
            [SERVICES[2], SERVICES[3]],
            [SERVICES[4], SERVICES[5]],
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )


def worker_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_REGISTER_WORKER],
            [BTN_MY_PROFILE],
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )


def profile_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ Исмни ўзгартириш",
                    callback_data="profile_edit:name",
                )
            ],
            [
                InlineKeyboardButton(
                    "📞 Телефонни ўзгартириш",
                    callback_data="profile_edit:phone",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔧 Хизматни ўзгартириш",
                    callback_data="profile_edit:service",
                )
            ],
            [
                InlineKeyboardButton(
                    "📍 Ҳудудни ўзгартириш",
                    callback_data="profile_edit:area",
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Нархни ўзгартириш",
                    callback_data="profile_edit:price",
                )
            ],
        ]
    )


def announcement_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )


def accept_order_keyboard(order_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Буюртмани қабул қилиш",
                    callback_data=f"accept_order:{order_id}",
                )
            ]
        ]
    )


# =========================================================
# START / HELP / CONTACT
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🛠 Osh Service ботга хуш келибсиз!\n\n"
        "Керакли хизматни танланг:",
        reply_markup=main_keyboard(),
    )

    return ConversationHandler.END


async def help_command(update, context):
    await update.message.reply_text(
        "🛠 Osh Service ёрдам\n\n"
        "🔧 Хизматлар — хизмат танлаш\n"
        "👨‍🔧 Уста чақириш — уста сифатида рўйхатдан ўтиш\n"
        "📢 Эълон бериш — эълон қолдириш\n"
        "Алоқа — администратор билан боғланиш"
    )


async def contact(update, context):
    await update.message.reply_text(
        "📞 Алоқа\n\n"
        "Osh Service администратори билан боғланиш учун "
        "Telegram орқали мурожаат қилинг."
    )


# =========================================================
# SERVICES
# =========================================================

async def services_menu(update, context):
    await update.message.reply_text(
        "🔧 Қайси хизмат керак?",
        reply_markup=services_keyboard(),
    )


# =========================================================
# WORKER MENU
# =========================================================

async def worker_menu(update, context):
    context.user_data.clear()

    await update.message.reply_text(
        "👨‍🔧 Уста чақириш бўлими\n\n"
        "Агар сиз хизмат кўрсатувчи уста бўлсангиз, "
        "бот орқали рўйхатдан ўтишингиз мумкин.",
        reply_markup=worker_keyboard(),
    )


# =========================================================
# CUSTOMER ORDER
# =========================================================

async def service_selected(update, context):
    service = update.message.text.strip()

    context.user_data["service"] = service

    workers = get_matching_workers(service)

    if workers:
        text = "👨‍🔧 Мос усталар:\n\n"

        for index, worker in enumerate(workers, start=1):
            text += (
                f"#{index} {worker['name']}\n"
                f"🔧 {worker['service']}\n"
                f"📍 {worker['area']}\n"
                f"💰 {worker['price']}\n"
                f"📞 {worker['phone']}\n\n"
            )

        await update.message.reply_text(
            text.strip()
        )

    else:
        await update.message.reply_text(
            "😔 Ҳозирча бу хизмат бўйича "
            "рўйхатдан ўтган уста топилмади."
        )

    await update.message.reply_text(
        f"Танланган хизмат: {service}\n\n"
        "👤 Исмингизни ёзинг:"
    )

    return CUSTOMER_NAME


async def customer_name(update, context):
    context.user_data["name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return CUSTOMER_PHONE


async def customer_phone(update, context):
    context.user_data["phone"] = update.message.text.strip()

    await update.message.reply_text(
        "📍 Манзилингизни ёзинг:"
    )

    return CUSTOMER_ADDRESS


async def customer_address(update, context):
    context.user_data["address"] = update.message.text.strip()

    await update.message.reply_text(
        "📝 Муаммони ёки сизга керак бўлган "
        "хизматни ёзинг:"
    )

    return CUSTOMER_PROBLEM


async def customer_problem(update, context):
    context.user_data["problem"] = update.message.text.strip()

    user = update.effective_user

    order_id = save_order(
        telegram_id=user.id,
        name=context.user_data["name"],
        phone=context.user_data["phone"],
        service=context.user_data["service"],
        address=context.user_data["address"],
        problem=context.user_data["problem"],
    )

    order_text = (
        "🔔 ЯНГИ БУЮРТМА!\n\n"
        f"🆔 Буюртма №: {order_id}\n"
        f"🔧 Хизмат: {context.user_data['service']}\n"
        f"👤 Исм: {context.user_data['name']}\n"
        f"📞 Телефон: {context.user_data['phone']}\n"
        f"📍 Манзил: {context.user_data['address']}\n"
        f"📝 Муаммо: {context.user_data['problem']}"
    )

    # Admin notification
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=order_text,
            )
        except Exception:
            logger.exception(
                "Admin notification failed"
            )

    # Worker notifications
    workers = get_matching_workers(
        context.user_data["service"]
    )

    notified_count = 0

    for worker in workers:
        try:
            await context.bot.send_message(
                chat_id=worker["telegram_id"],
                text=(
                    "🔔 СИЗГА ЯНГИ БУЮРТМА!\n\n"
                    f"🆔 Буюртма №: {order_id}\n"
                    f"🔧 Хизмат: {context.user_data['service']}\n"
                    f"👤 Мижоз: {context.user_data['name']}\n"
                    f"📞 Телефон: {context.user_data['phone']}\n"
                    f"📍 Манзил: {context.user_data['address']}\n"
                    f"📝 Муаммо: {context.user_data['problem']}\n\n"
                    "Мижоз билан телефон орқали "
                    "боғланишингиз мумкин."
                ),
                reply_markup=accept_order_keyboard(
                    order_id
                ),
            )

            notified_count += 1

        except Exception:
            logger.exception(
                "Worker notification failed: %s",
                worker["telegram_id"],
            )

    await update.message.reply_text(
        "✅ Буюртмангиз қабул қилинди!\n\n"
        f"👨‍🔧 {notified_count} та мос устага "
        "буюртма ҳақида хабар берилди.",
        reply_markup=main_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


# =========================================================
# WORKER REGISTRATION
# =========================================================

async def worker_register_start(update, context):
    context.user_data.clear()

    await update.message.reply_text(
        "👤 Исмингиз ва фамилиянгизни ёзинг:"
    )

    return WORKER_NAME


async def worker_name(update, context):
    context.user_data["worker_name"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return WORKER_PHONE


async def worker_phone(update, context):
    context.user_data["worker_phone"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "🔧 Қайси хизматни қиласиз?\n\n"
        "Масалан: сантехник, электрик, "
        "телефон таъмири"
    )

    return WORKER_SERVICE


async def worker_service(update, context):
    context.user_data["worker_service"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "📍 Қайси ҳудудда ишлайсиз?\n\n"
        "Масалан: Ош шаҳри, Навои кўчаси атрофи"
    )

    return WORKER_AREA


async def worker_area(update, context):
    context.user_data["worker_area"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "💰 Хизмат нархингизни ёзинг.\n\n"
        "Масалан: 500 сомдан бошланади"
    )

    return WORKER_PRICE


async def worker_price(update, context):
    context.user_data["worker_price"] = (
        update.message.text.strip()
    )

    user = update.effective_user

    save_worker(
        telegram_id=user.id,
        name=context.user_data["worker_name"],
        phone=context.user_data["worker_phone"],
        service=context.user_data["worker_service"],
        area=context.user_data["worker_area"],
        price=context.user_data["worker_price"],
    )

    worker_text = (
        "👨‍🔧 ЯНГИ УСТА РЎЙХАТДАН ЎТМОҚДА!\n\n"
        f"👤 Исм: {context.user_data['worker_name']}\n"
        f"📞 Телефон: {context.user_data['worker_phone']}\n"
        f"🔧 Хизмат: {context.user_data['worker_service']}\n"
        f"📍 Ҳудуд: {context.user_data['worker_area']}\n"
        f"💰 Нарх: {context.user_data['worker_price']}"
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=worker_text,
            )
        except Exception:
            logger.exception(
                "Worker admin notification failed"
            )

    await update.message.reply_text(
        worker_text
        + "\n\n"
        "✅ Маълумотларингиз қабул қилинди!\n\n"
        "Администратор маълумотларни текширади.\n\n"
        "📲 Telegram ID ҳам сақланди. "
        "Кейин мос буюртма келганда сизга "
        "Telegram орқали хабар юборилади.",
        reply_markup=main_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


# =========================================================
# WORKER PROFILE
# =========================================================

async def my_profile(update, context):
    context.user_data.clear()

    worker = get_worker_by_telegram_id(
        update.effective_user.id
    )

    if not worker:
        await update.message.reply_text(
            "😔 Сиз ҳали уста сифатида "
            "рўйхатдан ўтмагансиз.\n\n"
            "Аввал «👨‍🔧 Уста бўлиб рўйхатдан "
            "ўтиш» тугмасини босинг.",
            reply_markup=worker_keyboard(),
        )
        return

    await update.message.reply_text(
        "👤 МЕНИНГ ПРОФИЛИМ\n\n"
        f"👤 Исм: {worker['name']}\n"
        f"📞 Телефон: {worker['phone']}\n"
        f"🔧 Хизмат: {worker['service']}\n"
        f"📍 Ҳудуд: {worker['area']}\n"
        f"💰 Нарх: {worker['price']}\n\n"
        "Ўзгартириш учун керакли тугмани танланг:",
        reply_markup=profile_keyboard(),
    )


async def profile_edit_start(update, context):
    query = update.callback_query

    await query.answer()

    worker = get_worker_by_telegram_id(
        query.from_user.id
    )

    if not worker:
        await query.message.reply_text(
            "😔 Профилингиз топилмади."
        )
        return ConversationHandler.END

    field = query.data.split(":")[1]

    context.user_data["profile_field"] = field

    prompts = {
        "name": (
            "👤 Янги исм ва фамилиянгизни ёзинг:"
        ),
        "phone": (
            "📞 Янги телефон рақамингизни ёзинг:"
        ),
        "service": (
            "🔧 Янги хизматингизни ёзинг:\n\n"
            "Масалан: сантехник"
        ),
        "area": (
            "📍 Янги ҳудудингизни ёзинг:\n\n"
            "Масалан: Ош шаҳри"
        ),
        "price": (
            "💰 Янги хизмат нархингизни ёзинг:\n\n"
            "Масалан: 500 сомдан бошланади"
        ),
    }

    await query.message.reply_text(
        prompts.get(
            field,
            "Янги маълумотни ёзинг:"
        )
    )

    state_map = {
        "name": PROFILE_NAME,
        "phone": PROFILE_PHONE,
        "service": PROFILE_SERVICE,
        "area": PROFILE_AREA,
        "price": PROFILE_PRICE,
    }

    return state_map[field]


async def profile_name(update, context):
    return await save_profile_field(
        update,
        context,
        "name"
    )


async def profile_phone(update, context):
    return await save_profile_field(
        update,
        context,
        "phone"
    )


async def profile_service(update, context):
    return await save_profile_field(
        update,
        context,
        "service"
    )


async def profile_area(update, context):
    return await save_profile_field(
        update,
        context,
        "area"
    )


async def profile_price(update, context):
    return await save_profile_field(
        update,
        context,
        "price"
    )


async def save_profile_field(
    update,
    context,
    field
):
    value = update.message.text.strip()

    worker = get_worker_by_telegram_id(
        update.effective_user.id
    )

    if not worker:
        await update.message.reply_text(
            "😔 Профилингиз топилмади.",
            reply_markup=worker_keyboard(),
        )

        context.user_data.clear()

        return ConversationHandler.END

    update_worker_field(
        worker["id"],
        field,
        value
    )

    await update.message.reply_text(
        "✅ Маълумотингиз янгиланди!",
        reply_markup=worker_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


# =========================================================
# ANNOUNCEMENT
# =========================================================

async def announcement_start(update, context):
    context.user_data.clear()

    await update.message.reply_text(
        "📢 Эълон бериш\n\n"
        "👤 Исмингизни ёзинг:",
        reply_markup=announcement_keyboard(),
    )

    return ANNOUNCEMENT_NAME


async def announcement_name(update, context):
    context.user_data["announcement_name"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return ANNOUNCEMENT_PHONE


async def announcement_phone(update, context):
    context.user_data["announcement_phone"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "🔧 Қайси хизмат керак?"
    )

    return ANNOUNCEMENT_SERVICE


async def announcement_service(update, context):
    context.user_data["announcement_service"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "📍 Манзилингизни ёзинг:"
    )

    return ANNOUNCEMENT_ADDRESS


async def announcement_address(update, context):
    context.user_data["announcement_address"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "💰 Бюджетингизни ёзинг.\n\n"
        "Масалан: 1000 сомгача"
    )

    return ANNOUNCEMENT_BUDGET


async def announcement_budget(update, context):
    context.user_data["announcement_budget"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "📝 Қўшимча маълумот ёзинг:"
    )

    return ANNOUNCEMENT_DETAILS


async def announcement_details(update, context):
    context.user_data["announcement_details"] = (
        update.message.text.strip()
    )

    user = update.effective_user

    announcement_id = save_announcement(
        telegram_id=user.id,
        name=context.user_data["announcement_name"],
        phone=context.user_data["announcement_phone"],
        service=context.user_data["announcement_service"],
        address=context.user_data["announcement_address"],
        budget=context.user_data["announcement_budget"],
        details=context.user_data["announcement_details"],
    )

    announcement_text = (
        "📢 ЯНГИ ЭЪЛОН!\n\n"
        f"🆔 Эълон №: {announcement_id}\n"
        f"👤 Исм: {context.user_data['announcement_name']}\n"
        f"📞 Телефон: {context.user_data['announcement_phone']}\n"
        f"🔧 Хизмат: {context.user_data['announcement_service']}\n"
        f"📍 Манзил: {context.user_data['announcement_address']}\n"
        f"💰 Бюджет: {context.user_data['announcement_budget']}\n"
        f"📝 Маълумот: {context.user_data['announcement_details']}"
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=announcement_text,
            )
        except Exception:
            logger.exception(
                "Announcement notification failed"
            )

    await update.message.reply_text(
        "✅ Эълонингиз қабул қилинди!\n\n"
        "Администраторга юборилди.",
        reply_markup=main_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


# =========================================================
# ACCEPT ORDER
# =========================================================

async def accept_order(update, context):
    query = update.callback_query

    await query.answer()

    try:
        order_id = int(
            query.data.split(":")[1]
        )
    except (ValueError, IndexError):
        await query.answer(
            "Буюртма рақами нотўғри.",
            show_alert=True,
        )
        return

    worker_telegram_id = query.from_user.id

    worker = get_worker_by_telegram_id(
        worker_telegram_id
    )

    if not worker:
        await query.answer(
            "Сиз уста сифатида рўйхатдан ўтмагансиз.",
            show_alert=True,
        )
        return

    order = get_order(order_id)

    if not order:
        await query.answer(
            "Бундай буюртма топилмади.",
            show_alert=True,
        )
        return

    accepted = accept_order_in_db(
        order_id=order_id,
        worker_id=worker["id"],
        worker_name=worker["name"],
    )

    if not accepted:
        await query.answer(
            "Бу буюртма аллақачон қабул қилинган.",
            show_alert=True,
        )
        return

    try:
        await query.edit_message_text(
            query.message.text
            + "\n\n"
            "✅ СИЗ БУЮРТМАНИ ҚАБУЛ ҚИЛДИНГИЗ!"
        )
    except Exception:
        logger.exception(
            "Could not edit worker message"
        )

    # Notify customer
    try:
        await context.bot.send_message(
            chat_id=order["telegram_id"],
            text=(
                "✅ Буюртмангиз қабул қилинди!\n\n"
                f"👨‍🔧 Уста: {worker['name']}\n"
                f"🔧 Хизмат: {order['service']}\n"
                f"📞 Уста телефони: {worker['phone']}\n"
                f"📍 Уста ҳудуди: {worker['area']}\n"
                f"💰 Нарх: {worker['price']}\n\n"
                "Уста сиз билан телефон орқали "
                "боғланиши мумкин."
            ),
        )
    except Exception:
        logger.exception(
            "Could not notify customer"
        )

    # Notify admin
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "✅ БУЮРТМА ҚАБУЛ ҚИЛИНДИ!\n\n"
                    f"🆔 Буюртма №: {order_id}\n"
                    f"👨‍🔧 Уста: {worker['name']}\n"
                    f"📞 Уста: {worker['phone']}\n"
                    f"🔧 Хизмат: {order['service']}\n"
                    f"👤 Мижоз: {order['name']}\n"
                    f"📞 Мижоз: {order['phone']}\n"
                    f"📍 Манзил: {order['address']}\n"
                    f"📝 Муаммо: {order['problem']}"
                ),
            )
        except Exception:
            logger.exception(
                "Could not notify admin"
            )


# =========================================================
# ADMIN
# =========================================================

async def admin_command(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "❌ Сизда админ ҳуқуқи йўқ."
        )
        return

    keyboard = ReplyKeyboardMarkup(
        [
            ["👨‍🔧 Усталар", "📢 Эълонлар"],
            ["🔔 Буюртмалар", "📊 Статистика"],
            [BTN_BACK],
        ],
        resize_keyboard=True,
    )

    await update.message.reply_text(
        "👨‍💼 Админ панел",
        reply_markup=keyboard,
    )


async def admin_text(update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    text = update.message.text

    # STATISTICS
    if text == "📊 Статистика":

        stats = get_statistics()

        await update.message.reply_text(
            "📊 Статистика\n\n"
            f"👨‍🔧 Усталар: {stats['workers']}\n"
            f"📢 Эълонлар: {stats['announcements']}\n"
            f"🔔 Буюртмалар: {stats['orders']}\n"
            f"📦 Жами: {stats['total']}"
        )

    # WORKERS
    elif text == "👨‍🔧 Усталар":

        workers = get_all_workers()

        if not workers:
            await update.message.reply_text(
                "👨‍🔧 Ҳозирча усталар йўқ."
            )
            return

        result = "👨‍🔧 Усталар:\n\n"

        for worker in workers:
            result += (
                f"#{worker['id']} {worker['name']}\n"
                f"🔧 {worker['service']}\n"
                f"📍 {worker['area']}\n"
                f"💰 {worker['price']}\n"
                f"📞 {worker['phone']}\n\n"
            )

        await update.message.reply_text(
            result
        )

    # ANNOUNCEMENTS
    elif text == "📢 Эълонлар":

        announcements = get_all_announcements()

        if not announcements:
            await update.message.reply_text(
                "📢 Ҳозирча эълонлар йўқ."
            )
            return

        result = "📢 Эълонлар:\n\n"

        for item in announcements:
            result += (
                f"#{item['id']}\n"
                f"👤 {item['name']}\n"
                f"🔧 {item['service']}\n"
                f"📍 {item['address']}\n"
                f"💰 {item['budget']}\n"
                f"📝 {item['details']}\n\n"
            )

        await update.message.reply_text(
            result
        )

    # ORDERS
    elif text == "🔔 Буюртмалар":

        orders = get_all_orders()

        if not orders:
            await update.message.reply_text(
                "🔔 Ҳозирча буюртмалар йўқ."
            )
            return

        result = "🔔 Буюртмалар:\n\n"

        for order in orders:

            if order["status"] == "accepted":
                status_text = (
                    "✅ Қабул қилинган: "
                    f"{order['accepted_worker_name']}"
                )
            else:
                status_text = "⏳ Кутилмоқда"

            result += (
                f"#{order['id']} — {status_text}\n"
                f"🔧 {order['service']}\n"
                f"👤 {order['name']}\n"
                f"📞 {order['phone']}\n"
                f"📍 {order['address']}\n"
                f"📝 {order['problem']}\n\n"
            )

        await update.message.reply_text(
            result
        )


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def save_worker(
    telegram_id,
    name,
    phone,
    service,
    area,
    price
):
    conn = get_connection()

    conn.execute(
        """
        INSERT INTO workers
        (
            telegram_id,
            name,
            phone,
            service,
            area,
            price,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            telegram_id,
            name,
            phone,
            service,
            area,
            price,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        ),
    )

    conn.commit()
    conn.close()


def save_order(
    telegram_id,
    name,
    phone,
    service,
    address,
    problem
):
    conn = get_connection()

    cur = conn.execute(
        """
        INSERT INTO orders
        (
            telegram_id,
            name,
            phone,
            service,
            address,
            problem,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            telegram_id,
            name,
            phone,
            service,
            address,
            problem,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        ),
    )

    order_id = cur.lastrowid

    conn.commit()
    conn.close()

    return order_id


def save_announcement(
    telegram_id,
    name,
    phone,
    service,
    address,
    budget,
    details
):
    conn = get_connection()

    cur = conn.execute(
        """
        INSERT INTO announcements
        (
            telegram_id,
            name,
            phone,
            service,
            address,
            budget,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            telegram_id,
            name,
            phone,
            service,
            address,
            budget,
            details,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        ),
    )

    announcement_id = cur.lastrowid

    conn.commit()
    conn.close()

    return announcement_id


def get_matching_workers(service):
    wanted = normalize_service_name(service)

    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM workers ORDER BY id DESC"
    ).fetchall()

    conn.close()

    result = []

    for worker in rows:

        worker_service = normalize_service_name(
            worker["service"]
        )

        if wanted == worker_service:
            result.append(worker)

    return result


def get_worker_by_telegram_id(telegram_id):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM workers
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (telegram_id,),
    ).fetchone()

    conn.close()

    return row


def update_worker_field(
    worker_id,
    field,
    value
):
    allowed_fields = {
        "name",
        "phone",
        "service",
        "area",
        "price",
    }

    if field not in allowed_fields:
        return False

    conn = get_connection()

    query = f"""
        UPDATE workers
        SET {field} = ?
        WHERE id = ?
    """

    conn.execute(
        query,
        (value, worker_id)
    )

    conn.commit()
    conn.close()

    return True


def get_order(order_id):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE id = ?
        """,
        (order_id,),
    ).fetchone()

    conn.close()

    return row


def accept_order_in_db(
    order_id,
    worker_id,
    worker_name
):
    conn = get_connection()

    accepted_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cur = conn.execute(
        """
        UPDATE orders
        SET
            status = 'accepted',
            accepted_worker_id = ?,
            accepted_worker_name = ?,
            accepted_at = ?
        WHERE
            id = ?
            AND status = 'pending'
        """,
        (
            worker_id,
            worker_name,
            accepted_at,
            order_id,
        ),
    )

    conn.commit()

    changed = cur.rowcount > 0

    conn.close()

    return changed


def get_statistics():
    conn = get_connection()

    workers = conn.execute(
        "SELECT COUNT(*) AS count FROM workers"
    ).fetchone()["count"]

    announcements = conn.execute(
        "SELECT COUNT(*) AS count FROM announcements"
    ).fetchone()["count"]

    orders = conn.execute(
        "SELECT COUNT(*) AS count FROM orders"
    ).fetchone()["count"]

    conn.close()

    return {
        "workers": workers,
        "announcements": announcements,
        "orders": orders,
        "total": (
            workers
            + announcements
            + orders
        ),
    }


def get_all_workers():
    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM workers ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return rows


def get_all_announcements():
    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM announcements ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return rows


def get_all_orders():
    conn = get_connection()

    rows = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return rows


# =========================================================
# CUSTOMER CONVERSATION
# =========================================================

customer_conversation = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                "^🔧 (Сантехник|Электрик|"
                "Телефон таъмири|"
                "Компьютер таъмири|"
                "Уй тозалаш|"
                "Мебель таъмири)$"
            ),
            service_selected,
        )
    ],

    states={

        CUSTOMER_NAME: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                customer_name,
            )
        ],

        CUSTOMER_PHONE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                customer_phone,
            )
        ],

        CUSTOMER_ADDRESS: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                customer_address,
            )
        ],

        CUSTOMER_PROBLEM: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                customer_problem,
            )
        ],
    },

    fallbacks=[
        CommandHandler(
            "start",
            start
        ),
        MessageHandler(
            filters.Regex(
                f"^{BTN_BACK}$"
            ),
            start,
        ),
    ],

    allow_reentry=True,
)


# =========================================================
# WORKER CONVERSATION
# =========================================================

worker_conversation = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.Regex(
                f"^{BTN_REGISTER_WORKER}$"
            ),
            worker_register_start,
        )
    ],

    states={

        WORKER_NAME: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                worker_name,
            )
        ],

        WORKER_PHONE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                worker_phone,
            )
        ],

        WORKER_SERVICE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                worker_service,
            )
        ],

        WORKER_AREA: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                worker_area,
            )
        ],

        WORKER_PRICE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                worker_price,
            )
        ],
    },

    fallbacks=[
        CommandHandler(
            "start",
            start
        ),
        MessageHandler(
            filters.Regex(
                f"^{BTN_BACK}$"
            ),
            start,
        ),
    ],

    allow_reentry=True,
)


# =========================================================
# PROFILE CONVERSATION
# =========================================================

profile_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(
            profile_edit_start,
            pattern=r"^profile_edit:"
        )
    ],

    states={

        PROFILE_NAME: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                profile_name,
            )
        ],

        PROFILE_PHONE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                profile_phone,
            )
        ],

        PROFILE_SERVICE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                profile_service,
            )
        ],

        PROFILE_AREA: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                profile_area,
            )
        ],

        PROFILE_PRICE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                profile_price,
            )
        ],
    },

    fallbacks=[
        CommandHandler(
            "start",
            start
        ),
        MessageHandler(
            filters.Regex(
                f"^{BTN_BACK}$"
            ),
            start,
        ),
    ],

    allow_reentry=True,
)


# =========================================================
# ANNOUNCEMENT CONVERSATION
# =========================================================

announcement_conversation = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.Regex(
                f"^{BTN_ANNOUNCEMENT}$"
            ),
            announcement_start,
        )
    ],

    states={

        ANNOUNCEMENT_NAME: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                announcement_name,
            )
        ],

        ANNOUNCEMENT_PHONE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                announcement_phone,
            )
        ],

        ANNOUNCEMENT_SERVICE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                announcement_service,
            )
        ],

        ANNOUNCEMENT_ADDRESS: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                announcement_address,
            )
        ],

        ANNOUNCEMENT_BUDGET: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                announcement_budget,
            )
        ],

        ANNOUNCEMENT_DETAILS: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                announcement_details,
            )
        ],
    },

    fallbacks=[
        CommandHandler(
            "start",
            start
        ),
        MessageHandler(
            filters.Regex(
                f"^{BTN_BACK}$"
            ),
            start,
        ),
    ],

    allow_reentry=True,
)


# =========================================================
# MAIN
# =========================================================

def get_webhook_url():
    """
    Build the public Render webhook URL safely.
    """

    # 1. Preferred: Render's full URL
    if RENDER_EXTERNAL_URL:
        base_url = RENDER_EXTERNAL_URL.rstrip("/")

        return f"{base_url}/telegram"

    # 2. Fallback: Render hostname
    if RENDER_EXTERNAL_HOSTNAME:
        hostname = RENDER_EXTERNAL_HOSTNAME.strip()

        if hostname.startswith("http://"):
            base_url = hostname

        elif hostname.startswith("https://"):
            base_url = hostname

        else:
            base_url = f"https://{hostname}"

        return f"{base_url.rstrip('/')}/telegram"

    # 3. Final fallback for this Render service
    return "https://tez-service-bot.onrender.com/telegram"


def build_application():
    """
    Creates the Telegram application and registers all handlers.
    """

    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is missing."
        )

    init_db()

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    # -----------------------------------------------------
    # Order acceptance
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            accept_order,
            pattern=r"^accept_order:\d+$",
        )
    )

    # -----------------------------------------------------
    # Main menu
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Regex(
                f"^{BTN_SERVICES}$"
            ),
            services_menu,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                f"^{BTN_WORKER}$"
            ),
            worker_menu,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                f"^{BTN_CONTACT}$"
            ),
            contact,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                f"^{BTN_MY_PROFILE}$"
            ),
            my_profile,
        )
    )

    # -----------------------------------------------------
    # Conversations
    # -----------------------------------------------------

    application.add_handler(
        customer_conversation
    )

    application.add_handler(
        worker_conversation
    )

    application.add_handler(
        profile_conversation
    )

    application.add_handler(
        announcement_conversation
    )

    # -----------------------------------------------------
    # Back button
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Regex(
                f"^{BTN_BACK}$"
            ),
            start,
        )
    )

    # -----------------------------------------------------
    # Admin text
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_text,
        )
    )

    return application


def main():

    logger.info(
        "Starting Osh Service bot..."
    )

    logger.info(
        "Render PORT: %s",
        PORT
    )

    application = build_application()

    webhook_url = get_webhook_url()

    logger.info(
        "Starting webhook server..."
    )

    logger.info(
        "Webhook path: /telegram"
    )

    # IMPORTANT:
    # Render requires the server to listen on 0.0.0.0.
    #
    # bootstrap_retries=-1 means PTB keeps retrying
    # Telegram webhook setup if Telegram is temporarily
    # unreachable.
    #
    # Render provides HTTPS externally, while the internal
    # application listens on HTTP.
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="telegram",
        webhook_url=webhook_url,
        drop_pending_updates=True,
        bootstrap_retries=-1,
        allowed_updates=Update.ALL_TYPES,
        max_connections=40,
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
