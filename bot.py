import os
import re
import sqlite3
import logging
import unicodedata
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


# ============================================================
# SETTINGS
# ============================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID is not configured")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise RuntimeError("ADMIN_ID must be a number")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "bot.db")


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name TEXT,
            phone TEXT,
            service TEXT,
            area TEXT,
            price TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name TEXT,
            phone TEXT,
            service TEXT,
            address TEXT,
            problem TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name TEXT,
            phone TEXT,
            service TEXT,
            address TEXT,
            budget TEXT,
            details TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# SERVICES
# ============================================================

SERVICES = [
    "🔧 Сантехник",
    "⚡ Электрик",
    "📱 Телефон таъмири",
    "💻 Компьютер таъмири",
    "🧹 Уй тозалаш",
    "🪑 Мебель таъмири",
]


# ============================================================
# SERVICE NORMALIZATION
# ============================================================

def normalize_service_name(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.casefold().strip()

    # Remove emojis and symbols
    cleaned = []

    for char in text:
        category = unicodedata.category(char)

        if category.startswith("So"):
            continue

        cleaned.append(char)

    text = "".join(cleaned)

    # Cyrillic -> Latin
    replacements = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "j",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "x",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sh",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "қ": "q",
        "ғ": "g",
        "ў": "u",
        "ҳ": "h",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Uzbek variations
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = text.replace("`", "")
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def service_matches(worker_service, selected_service):
    a = normalize_service_name(worker_service)
    b = normalize_service_name(selected_service)

    if not a or not b:
        return False

    if a == b:
        return True

    # Allow common word variations
    if a in b or b in a:
        return True

    return False


def get_matching_workers(service):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM workers ORDER BY id DESC"
    ).fetchall()
    conn.close()

    result = []

    for row in rows:
        if service_matches(row["service"], service):
            result.append(row)

    return result


# ============================================================
# KEYBOARDS
# ============================================================

BTN_SERVICES = "🔧 Хизматлар"
BTN_WORKER = "👨‍🔧 Уста чақириш"
BTN_ANNOUNCEMENT = "📢 Эълон бериш"
BTN_CONTACT = "Алоқа"
BTN_PROFILE = "👤 Менинг профилим"
BTN_BACK = "⬅️ Орқага"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_SERVICES)],
        [KeyboardButton(BTN_WORKER)],
        [KeyboardButton(BTN_ANNOUNCEMENT)],
        [KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_CONTACT)],
    ],
    resize_keyboard=True,
)


def services_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(SERVICES[0]), KeyboardButton(SERVICES[1])],
            [KeyboardButton(SERVICES[2]), KeyboardButton(SERVICES[3])],
            [KeyboardButton(SERVICES[4]), KeyboardButton(SERVICES[5])],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True,
    )


WORKER_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("👨‍🔧 Уста бўлиб рўйхатдан ўтиш")],
        [KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_BACK)],
    ],
    resize_keyboard=True,
)


# ============================================================
# START / HELP
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 Osh Service ботга хуш келибсиз!\n\n"
        "Керакли хизматни танланг:",
        reply_markup=MAIN_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Ботдан фойдаланиш:\n\n"
        "🔧 Хизматлар — керакли хизматни танлаш\n"
        "👨‍🔧 Уста чақириш — уста бўлиб рўйхатдан ўтиш\n"
        "📢 Эълон бериш — хизматга буюртма бериш\n"
        "👤 Менинг профилим — уста профили\n"
        "Алоқа — админ билан боғланиш"
    )


# ============================================================
# MAIN MENU
# ============================================================

async def services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔧 Қайси хизмат керак?",
        reply_markup=services_keyboard(),
    )


async def worker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍🔧 Уста чақириш бўлими\n\n"
        "Агар сиз хизмат кўрсатувчи уста бўлсангиз, "
        "рўйхатдан ўтинг.",
        reply_markup=WORKER_KEYBOARD,
    )


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 Алоқа учун администраторга мурожаат қилинг."
    )


# ============================================================
# CUSTOMER ORDER
# ============================================================

CUSTOMER_NAME, CUSTOMER_PHONE, CUSTOMER_ADDRESS, CUSTOMER_PROBLEM = range(4)


# IMPORTANT:
# Service pattern is created automatically from SERVICES.
# This is more reliable than manually writing the emoji regex.

SERVICE_PATTERN = (
    r"^(?:"
    + "|".join(re.escape(service) for service in SERVICES)
    + r")$"
)


async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        service = update.message.text.strip()

        logger.info("Service selected: %s", service)

        # Save selected service
        context.user_data["service"] = service

        # Find workers
        try:
            workers = get_matching_workers(service)
        except Exception:
            logger.exception("Worker matching error")
            workers = []

        if workers:
            text = "👨‍🔧 Мос усталар:\n\n"

            for index, worker in enumerate(workers[:10], start=1):
                text += (
                    f"{index}. {worker['name']}\n"
                    f"🔧 Хизмат: {worker['service']}\n"
                    f"📍 Ҳудуд: {worker['area']}\n"
                    f"💰 Нархи: {worker['price']}\n"
                    f"📞 Телефон: {worker['phone']}\n\n"
                )

            await update.message.reply_text(text)

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

    except Exception:
        logger.exception("service_selected failed")

        await update.message.reply_text(
            "⚠️ Хизматни қабул қилишда хатолик юз берди.\n\n"
            "Илтимос, исмингизни ёзинг:"
        )

        return CUSTOMER_NAME


async def customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return CUSTOMER_PHONE


async def customer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()

    await update.message.reply_text(
        "📍 Манзилингизни ёзинг:"
    )

    return CUSTOMER_ADDRESS


async def customer_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text.strip()

    await update.message.reply_text(
        "📝 Муаммони қисқача ёзинг:"
    )

    return CUSTOMER_PROBLEM


async def customer_problem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["problem"] = update.message.text.strip()

    service = context.user_data.get("service", "")
    name = context.user_data.get("name", "")
    phone = context.user_data.get("phone", "")
    address = context.user_data.get("address", "")
    problem = context.user_data.get("problem", "")

    conn = get_db()

    conn.execute(
        """
        INSERT INTO orders
        (telegram_id, name, phone, service, address, problem, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            update.effective_user.id,
            name,
            phone,
            service,
            address,
            problem,
            now_text(),
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🔔 ЯНГИ БУЮРТМА!\n\n"
        f"👤 Исм: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"🔧 Хизмат: {service}\n"
        f"📍 Манзил: {address}\n"
        f"📝 Муаммо: {problem}"
    )

    await update.message.reply_text(
        "✅ Буюртмангиз қабул қилинди.\n"
        "Тез орада мос уста билан боғланишингиз мумкин.",
        reply_markup=MAIN_KEYBOARD,
    )

    context.user_data.clear()

    return ConversationHandler.END


async def customer_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Буюртма бекор қилинди.",
        reply_markup=MAIN_KEYBOARD,
    )

    return ConversationHandler.END


customer_conversation = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.TEXT & filters.Regex(SERVICE_PATTERN),
            service_selected,
        )
    ],
    states={
        CUSTOMER_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name)
        ],
        CUSTOMER_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, customer_phone)
        ],
        CUSTOMER_ADDRESS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, customer_address)
        ],
        CUSTOMER_PROBLEM: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, customer_problem)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", customer_cancel),
    ],
    allow_reentry=True,
)


# ============================================================
# WORKER REGISTRATION
# ============================================================

WORKER_NAME, WORKER_PHONE, WORKER_SERVICE, WORKER_AREA, WORKER_PRICE = range(5, 10)


async def worker_register_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "👤 Исм ва фамилиянгизни ёзинг:"
    )

    return WORKER_NAME


async def worker_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["worker_name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return WORKER_PHONE


async def worker_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["worker_phone"] = update.message.text.strip()

    await update.message.reply_text(
        "🔧 Қайси хизматларни кўрсатасиз?\n\n"
        "Масалан:\n"
        "Santehnik, kafel, ariston, unitaz"
    )

    return WORKER_SERVICE


async def worker_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["worker_service"] = update.message.text.strip()

    await update.message.reply_text(
        "📍 Қайси ҳудудда ишлайсиз?"
    )

    return WORKER_AREA


async def worker_area(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["worker_area"] = update.message.text.strip()

    await update.message.reply_text(
        "💰 Хизмат нархини ёзинг.\n\n"
        "Масалан: 500 сомдан бошлаб"
    )

    return WORKER_PRICE


async def worker_price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["worker_price"] = update.message.text.strip()

    name = context.user_data.get("worker_name", "")
    phone = context.user_data.get("worker_phone", "")
    service = context.user_data.get("worker_service", "")
    area = context.user_data.get("worker_area", "")
    price = context.user_data.get("worker_price", "")

    conn = get_db()

    conn.execute(
        """
        INSERT INTO workers
        (telegram_id, name, phone, service, area, price, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            update.effective_user.id,
            name,
            phone,
            service,
            area,
            price,
            now_text(),
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Сиз уста сифатида муваффақиятли рўйхатдан ўтдингиз!\n\n"
        f"👤 {name}\n"
        f"📞 {phone}\n"
        f"🔧 {service}\n"
        f"📍 {area}\n"
        f"💰 {price}",
        reply_markup=MAIN_KEYBOARD,
    )

    context.user_data.clear()

    return ConversationHandler.END


async def worker_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Рўйхатдан ўтиш бекор қилинди.",
        reply_markup=MAIN_KEYBOARD,
    )

    return ConversationHandler.END


worker_conversation = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.Regex(
                "^👨‍🔧 Уста бўлиб рўйхатдан ўтиш$"
            ),
            worker_register_start,
        )
    ],
    states={
        WORKER_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, worker_name)
        ],
        WORKER_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, worker_phone)
        ],
        WORKER_SERVICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, worker_service)
        ],
        WORKER_AREA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, worker_area)
        ],
        WORKER_PRICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, worker_price)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", worker_cancel)
    ],
    allow_reentry=True,
)


# ============================================================
# ANNOUNCEMENT
# ============================================================

ANN_NAME, ANN_PHONE, ANN_SERVICE, ANN_ADDRESS, ANN_BUDGET, ANN_DETAILS = range(10, 16)


async def announcement_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "👤 Исмингизни ёзинг:"
    )

    return ANN_NAME


async def announcement_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["ann_name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return ANN_PHONE


async def announcement_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["ann_phone"] = update.message.text.strip()

    await update.message.reply_text(
        "🔧 Қайси хизмат керак?"
    )

    return ANN_SERVICE


async def announcement_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["ann_service"] = update.message.text.strip()

    await update.message.reply_text(
        "📍 Манзилни ёзинг:"
    )

    return ANN_ADDRESS


async def announcement_address(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["ann_address"] = update.message.text.strip()

    await update.message.reply_text(
        "💰 Бюджетингизни ёзинг:"
    )

    return ANN_BUDGET


async def announcement_budget(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["ann_budget"] = update.message.text.strip()

    await update.message.reply_text(
        "📝 Тафсилотни ёзинг:"
    )

    return ANN_DETAILS


async def announcement_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["ann_details"] = update.message.text.strip()

    name = context.user_data.get("ann_name", "")
    phone = context.user_data.get("ann_phone", "")
    service = context.user_data.get("ann_service", "")
    address = context.user_data.get("ann_address", "")
    budget = context.user_data.get("ann_budget", "")
    details = context.user_data.get("ann_details", "")

    conn = get_db()

    conn.execute(
        """
        INSERT INTO announcements
        (telegram_id, name, phone, service, address, budget, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            update.effective_user.id,
            name,
            phone,
            service,
            address,
            budget,
            details,
            now_text(),
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "📢 ЯНГИ ЭЪЛОН!\n\n"
        f"👤 Исм: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"🔧 Хизмат: {service}\n"
        f"📍 Манзил: {address}\n"
        f"💰 Бюджет: {budget}\n"
        f"📝 Тафсилот: {details}"
    )

    await update.message.reply_text(
        "✅ Эълонингиз қабул қилинди.",
        reply_markup=MAIN_KEYBOARD,
    )

    context.user_data.clear()

    return ConversationHandler.END


async def announcement_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Эълон бериш бекор қилинди.",
        reply_markup=MAIN_KEYBOARD,
    )

    return ConversationHandler.END


announcement_conversation = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.Regex(
                "^📢 Эълон бериш$"
            ),
            announcement_start,
        )
    ],
    states={
        ANN_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_name)
        ],
        ANN_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_phone)
        ],
        ANN_SERVICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_service)
        ],
        ANN_ADDRESS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_address)
        ],
        ANN_BUDGET: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_budget)
        ],
        ANN_DETAILS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, announcement_details)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", announcement_cancel)
    ],
    allow_reentry=True,
)


# ============================================================
# MY PROFILE
# ============================================================

async def my_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    conn = get_db()

    worker = conn.execute(
        """
        SELECT * FROM workers
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (update.effective_user.id,),
    ).fetchone()

    conn.close()

    if not worker:
        await update.message.reply_text(
            "👤 Сизнинг уста профилингиз ҳозирча топилмади.\n\n"
            "👨‍🔧 Уста чақириш → "
            "👨‍🔧 Уста бўлиб рўйхатдан ўтиш"
        )
        return

    await update.message.reply_text(
        "👤 Менинг профилим\n\n"
        f"👨‍🔧 Исм: {worker['name']}\n"
        f"📞 Телефон: {worker['phone']}\n"
        f"🔧 Хизмат: {worker['service']}\n"
        f"📍 Ҳудуд: {worker['area']}\n"
        f"💰 Нархи: {worker['price']}"
    )


# ============================================================
# ADMIN
# ============================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Сизда админ ҳуқуқи йўқ."
        )
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👨‍🔧 Усталар",
                    callback_data="admin_workers",
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 Эълонлар",
                    callback_data="admin_announcements",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔔 Буюртмалар",
                    callback_data="admin_orders",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Статистика",
                    callback_data="admin_stats",
                )
            ],
        ]
    )

    await update.message.reply_text(
        "🔐 Админ панель",
        reply_markup=keyboard,
    )


async def admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text(
            "⛔ Сизда админ ҳуқуқи йўқ."
        )
        return

    conn = get_db()

    if query.data == "admin_workers":

        rows = conn.execute(
            "SELECT * FROM workers ORDER BY id DESC LIMIT 20"
        ).fetchall()

        if not rows:
            text = "👨‍🔧 Ҳозирча усталар йўқ."
        else:
            text = "👨‍🔧 Усталар:\n\n"

            for i, row in enumerate(rows, 1):
                text += (
                    f"{i}. {row['name']}\n"
                    f"🔧 {row['service']}\n"
                    f"📍 {row['area']}\n"
                    f"💰 {row['price']}\n"
                    f"📞 {row['phone']}\n\n"
                )

        await query.edit_message_text(text)

    elif query.data == "admin_announcements":

        rows = conn.execute(
            """
            SELECT * FROM announcements
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

        if not rows:
            text = "📢 Ҳозирча эълонлар йўқ."
        else:
            text = "📢 Эълонлар:\n\n"

            for i, row in enumerate(rows, 1):
                text += (
                    f"{i}. {row['name']}\n"
                    f"🔧 {row['service']}\n"
                    f"📍 {row['address']}\n"
                    f"💰 {row['budget']}\n"
                    f"📝 {row['details']}\n\n"
                )

        await query.edit_message_text(text)

    elif query.data == "admin_orders":

        rows = conn.execute(
            """
            SELECT * FROM orders
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

        if not rows:
            text = "🔔 Ҳозирча буюртмалар йўқ."
        else:
            text = "🔔 Буюртмалар:\n\n"

            for i, row in enumerate(rows, 1):
                text += (
                    f"{i}. {row['name']}\n"
                    f"🔧 {row['service']}\n"
                    f"📍 {row['address']}\n"
                    f"📝 {row['problem']}\n"
                    f"📞 {row['phone']}\n\n"
                )

        await query.edit_message_text(text)

    elif query.data == "admin_stats":

        workers = conn.execute(
            "SELECT COUNT(*) FROM workers"
        ).fetchone()[0]

        announcements = conn.execute(
            "SELECT COUNT(*) FROM announcements"
        ).fetchone()[0]

        orders = conn.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        total = workers + announcements + orders

        await query.edit_message_text(
            "📊 Статистика\n\n"
            f"👨‍🔧 Усталар: {workers}\n"
            f"📢 Эълонлар: {announcements}\n"
            f"🔔 Буюртмалар: {orders}\n"
            f"📈 Жами: {total}"
        )

    conn.close()


# ============================================================
# BACK BUTTON
# ============================================================

async def back_to_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "🛠 Асосий меню:",
        reply_markup=MAIN_KEYBOARD,
    )


# ============================================================
# CATCH-ALL
# ============================================================

async def unknown_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "Илтимос, менюдаги керакли тугмани танланг.",
        reply_markup=MAIN_KEYBOARD,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    init_db()

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    # Admin callbacks
    application.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern="^admin_"
        )
    )

    # IMPORTANT:
    # Conversation handlers are added BEFORE catch-all.
    application.add_handler(
        customer_conversation
    )

    application.add_handler(
        worker_conversation
    )

    application.add_handler(
        announcement_conversation
    )

    # Main menu
    application.add_handler(
        MessageHandler(
            filters.Regex(f"^{re.escape(BTN_SERVICES)}$"),
            services_menu,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(f"^{re.escape(BTN_WORKER)}$"),
            worker_menu,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(f"^{re.escape(BTN_PROFILE)}$"),
            my_profile,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(f"^{re.escape(BTN_CONTACT)}$"),
            contact,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(f"^{re.escape(BTN_BACK)}$"),
            back_to_start,
        )
    )

    # Catch-all must be LAST
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            unknown_text,
        )
    )

    logger.info("Osh Service bot starting")

    # Render Web Service
    if RENDER_EXTERNAL_URL:

        webhook_url = (
            RENDER_EXTERNAL_URL.rstrip("/")
            + "/telegram"
        )

        logger.info(
            "Starting webhook on port %s",
            PORT
        )

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="telegram",
            webhook_url=webhook_url,
        )

    else:

        logger.info(
            "Starting polling mode"
        )

        application.run_polling()


if __name__ == "__main__":
    main()
