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


# =========================
# SETTINGS
# =========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "bot.db")


# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# BUTTONS
# =========================

BTN_SERVICES = "🔧 Хизматлар"
BTN_WORKER = "👨‍🔧 Уста чақириш"
BTN_ANNOUNCEMENT = "📢 Эълон бериш"
BTN_CONTACT = "Алоқа"
BTN_BACK = "⬅️ Орқага"

BTN_REGISTER_WORKER = "👨‍🔧 Уста бўлиб рўйхатдан ўтиш"


# =========================
# SERVICES
# =========================

SERVICES = [
    "🔧 Сантехник",
    "⚡ Электрик",
    "📱 Телефон таъмири",
    "💻 Компьютер таъмири",
    "🧹 Уй тозалаш",
    "🪑 Мебель таъмири",
]


# =========================
# CONVERSATION STATES
# =========================

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


# =========================
# DATABASE
# =========================

def get_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
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
        """
    )

    cur.execute(
        """
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
        """
    )

    cur.execute(
        """
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
        """
    )

    conn.commit()

    # Existing databases may not have the new order columns.
    # Add them safely if necessary.
    columns = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(orders)").fetchall()
    }

    if "status" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )

    if "accepted_worker_id" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN accepted_worker_id INTEGER"
        )

    if "accepted_worker_name" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN accepted_worker_name TEXT"
        )

    if "accepted_at" not in columns:
        cur.execute(
            "ALTER TABLE orders ADD COLUMN accepted_at TEXT"
        )

    conn.commit()
    conn.close()


# =========================
# TEXT NORMALIZATION
# =========================

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

    emoji_chars = [
        "🔧",
        "⚡",
        "📱",
        "💻",
        "🧹",
        "🪑",
    ]

    for emoji in emoji_chars:
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


# =========================
# KEYBOARDS
# =========================

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
            [BTN_BACK],
        ],
        resize_keyboard=True,
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


# =========================
# BASIC MENUS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🛠 Osh Service ботга хуш келибсиз!\n\n"
        "Керакли хизматни танланг:",
        reply_markup=main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 Osh Service ёрдам\n\n"
        "🔧 Хизматлар — хизмат танлаш\n"
        "👨‍🔧 Уста чақириш — уста сифатида рўйхатдан ўтиш\n"
        "📢 Эълон бериш — хизмат учун эълон қолдириш\n\n"
        "Саволлар бўлса, «Алоқа» бўлими орқали мурожаат қилинг."
    )


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 Алоқа\n\n"
        "Osh Service администратори билан боғланиш учун "
        "Telegram орқали мурожаат қилинг."
    )


async def services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔧 Қайси хизмат керак?",
        reply_markup=services_keyboard(),
    )


async def worker_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍🔧 Уста чақириш бўлими\n\n"
        "Агар сиз хизмат кўрсатувчи уста бўлсангиз, "
        "бот орқали рўйхатдан ўтишингиз мумкин.",
        reply_markup=worker_keyboard(),
    )


# =========================
# CUSTOMER ORDER
# =========================

async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        await update.message.reply_text(text.strip())

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
        "📝 Муаммони ёки сизга керак бўлган хизматни ёзинг:"
    )

    return CUSTOMER_PROBLEM


async def customer_problem(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"🔧 Хизмат: {context.user_data['service']}\n"
        f"👤 Исм: {context.user_data['name']}\n"
        f"📞 Телефон: {context.user_data['phone']}\n"
        f"📍 Манзил: {context.user_data['address']}\n"
        f"📝 Муаммо: {context.user_data['problem']}\n"
        f"🆔 Буюртма №: {order_id}"
    )

    # Admin notification
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=order_text,
            )
        except Exception:
            logger.exception("Could not notify admin about order")

    # Matching workers
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
                    "Мижоз билан телефон орқали боғланишингиз мумкин."
                ),
                reply_markup=accept_order_keyboard(order_id),
            )

            notified_count += 1

        except Exception:
            logger.exception(
                "Could not notify worker %s",
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


# =========================
# WORKER REGISTRATION
# =========================

async def worker_register_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "👤 Исмингиз ва фамилиянгизни ёзинг:"
    )

    return WORKER_NAME


async def worker_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["worker_name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return WORKER_PHONE


async def worker_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["worker_phone"] = update.message.text.strip()

    await update.message.reply_text(
        "🔧 Қайси хизматни қиласиз?\n\n"
        "Масалан: сантехник, электрик, телефон таъмири"
    )

    return WORKER_SERVICE


async def worker_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["worker_service"] = update.message.text.strip()

    await update.message.reply_text(
        "📍 Қайси ҳудудда ишлайсиз?\n\n"
        "Масалан: Ош шаҳри, Навои кўчаси атрофи"
    )

    return WORKER_AREA


async def worker_area(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["worker_area"] = update.message.text.strip()

    await update.message.reply_text(
        "💰 Хизмат нархингизни ёзинг.\n\n"
        "Масалан: 500 сомдан бошланади"
    )

    return WORKER_PRICE


async def worker_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["worker_price"] = update.message.text.strip()

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
            logger.exception("Could not notify admin about worker")

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


# =========================
# ANNOUNCEMENTS
# =========================

async def announcement_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "📢 Эълон бериш\n\n"
        "👤 Исмингизни ёзинг:",
        reply_markup=announcement_keyboard(),
    )

    return ANNOUNCEMENT_NAME


async def announcement_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["announcement_name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return ANNOUNCEMENT_PHONE


async def announcement_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["announcement_phone"] = update.message.text.strip()

    await update.message.reply_text(
        "🔧 Қайси хизмат керак?"
    )

    return ANNOUNCEMENT_SERVICE
