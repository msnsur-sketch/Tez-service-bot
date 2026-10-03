import logging
import os
import sqlite3
import unicodedata
from datetime import datetime

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
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
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "bot.db"
)

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
BTN_BACK = "⬅️ Орқага"
BTN_REGISTER_WORKER = "👨‍🔧 Уста бўлиб рўйхатдан ўтиш"


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

# Customer
CUSTOMER_NAME = 0
CUSTOMER_PHONE = 1
CUSTOMER_ADDRESS = 2
CUSTOMER_PROBLEM = 3

# Worker
WORKER_NAME = 10
WORKER_PHONE = 11
WORKER_SERVICE = 12
WORKER_AREA = 13
WORKER_PRICE = 14

# Announcement
ANN_NAME = 20
ANN_PHONE = 21
ANN_SERVICE = 22
ANN_ADDRESS = 23
ANN_BUDGET = 24
ANN_DETAILS = 25


# =========================
# DATABASE
# =========================

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
            telegram_id INTEGER,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service TEXT NOT NULL,
            address TEXT NOT NULL,
            problem TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
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

    # Old database compatibility
    columns = [
        row["name"]
        for row in cur.execute("PRAGMA table_info(workers)").fetchall()
    ]

    if "telegram_id" not in columns:
        cur.execute("ALTER TABLE workers ADD COLUMN telegram_id INTEGER")
        conn.commit()

    columns = [
        row["name"]
        for row in cur.execute("PRAGMA table_info(orders)").fetchall()
    ]

    if "telegram_id" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN telegram_id INTEGER")
        conn.commit()

    columns = [
        row["name"]
        for row in cur.execute("PRAGMA table_info(announcements)").fetchall()
    ]

    if "telegram_id" not in columns:
        cur.execute(
            "ALTER TABLE announcements ADD COLUMN telegram_id INTEGER"
        )
        conn.commit()

    conn.close()


# =========================
# NORMALIZATION
# =========================

def normalize_text(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.casefold().strip()

    replacements = {
        "ё": "е",
        "ў": "у",
        "ғ": "г",
        "қ": "к",
        "ҳ": "х",
        "ҷ": "ж",
        "ҳ": "х",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return " ".join(text.split())


def normalize_service_name(service):
    text = normalize_text(service)

    # Remove common emojis
    for emoji in ["🔧", "⚡", "📱", "💻", "🧹", "🪑"]:
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
# DATABASE FUNCTIONS
# =========================

def save_worker(
    telegram_id,
    name,
    phone,
    service,
    area,
    price,
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM workers WHERE phone = ?",
        (phone,)
    )

    existing = cur.fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        cur.execute("""
            UPDATE workers
            SET telegram_id = ?,
                name = ?,
                service = ?,
                area = ?,
                price = ?,
                created_at = ?
            WHERE id = ?
        """, (
            telegram_id,
            name,
            service,
            area,
            price,
            now,
            existing["id"],
        ))
    else:
        cur.execute("""
            INSERT INTO workers
            (telegram_id, name, phone, service, area, price, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            telegram_id,
            name,
            phone,
            service,
            area,
            price,
            now,
        ))

    conn.commit()
    conn.close()


def save_order(
    telegram_id,
    name,
    phone,
    service,
    address,
    problem,
):
    conn = get_db()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO orders
        (telegram_id, name, phone, service, address, problem, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        telegram_id,
        name,
        phone,
        service,
        address,
        problem,
        now,
    ))

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
    details,
):
    conn = get_db()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO announcements
        (telegram_id, name, phone, service, address, budget, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        telegram_id,
        name,
        phone,
        service,
        address,
        budget,
        details,
        now,
    ))

    announcement_id = cur.lastrowid

    conn.commit()
    conn.close()

    return announcement_id


def get_matching_workers(service):
    wanted = normalize_service_name(service)

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM workers ORDER BY id DESC"
    ).fetchall()
    conn.close()

    result = []

    for worker in rows:
        worker_service = worker["service"] or ""

        # Worker can have several services separated by comma
        services = [
            normalize_service_name(x)
            for x in worker_service.replace(";", ",").split(",")
        ]

        if wanted in services or wanted == normalize_service_name(worker_service):
            result.append(worker)

    return result


def get_statistics():
    conn = get_db()

    workers = conn.execute(
        "SELECT COUNT(*) FROM workers"
    ).fetchone()[0]

    orders = conn.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0]

    announcements = conn.execute(
        "SELECT COUNT(*) FROM announcements"
    ).fetchone()[0]

    conn.close()

    return workers, orders, announcements


# =========================
# MAIN MENU
# =========================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_SERVICES],
            [BTN_WORKER],
            [BTN_ANNOUNCEMENT],
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


# =========================
# START
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
        "🛠 Osh Service\n\n"
        "🔧 Хизматлар — хизмат буюртма қилиш\n"
        "👨‍🔧 Уста чақириш — уста сифатида рўйхатдан ўтиш\n"
        "📢 Эълон бериш — хизмат ҳақида эълон бериш"
    )


# =========================
# SERVICES
# =========================

async def services_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "🔧 Қайси хизмат керак?",
        reply_markup=services_keyboard(),
    )


async def service_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    service = update.message.text

    # Only accept actual service buttons
    if service not in SERVICES:
        return

    context.user_data["service"] = service

    workers = get_matching_workers(service)

    if workers:
        text = "👨‍🔧 Мос усталар:\n\n"

        for i, worker in enumerate(workers[:10], start=1):
            text += (
                f"#{i} {worker['name']}\n"
                f"🔧 {worker['service']}\n"
                f"📍 {worker['area']}\n"
                f"💰 {worker['price']}\n"
            )

            if worker["phone"]:
                text += f"📞 {worker['phone']}\n"

            text += "\n"

        text += (
            f"Танланган хизмат: {service}\n\n"
            "👤 Исмингизни ёзинг:"
        )

        await update.message.reply_text(
            text,
            reply_markup=ReplyKeyboardMarkup(
                [[BTN_BACK]],
                resize_keyboard=True,
            ),
        )

    else:
        await update.message.reply_text(
            "😔 Ҳозирча бу хизмат бўйича "
            "рўйхатдан ўтган уста топилмади.\n\n"
            f"Танланган хизмат: {service}\n\n"
            "👤 Исмингизни ёзинг:",
            reply_markup=ReplyKeyboardMarkup(
                [[BTN_BACK]],
                resize_keyboard=True,
            ),
        )

    return CUSTOMER_NAME


async def customer_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.message.text == BTN_BACK:
        return await start(update, context)

    context.user_data["name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return CUSTOMER_PHONE


async def customer_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.message.text == BTN_BACK:
        return await start(update, context)

    context.user_data["phone"] = update.message.text.strip()

    await update.message.reply_text(
        "📍 Манзилингизни ёзинг:"
    )

    return CUSTOMER_ADDRESS


async def customer_address(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.message.text == BTN_BACK:
        return await start(update, context)

    context.user_data["address"] = update.message.text.strip()

    await update.message.reply_text(
        "📝 Муаммони ёки сизга керак бўлган хизматни ёзинг:"
    )

    return CUSTOMER_PROBLEM


async def customer_problem(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.message.text == BTN_BACK:
        return await start(update, context)

    problem = update.message.text.strip()
    context.user_data["problem"] = problem

    service = context.user_data["service"]
    name = context.user_data["name"]
    phone = context.user_data["phone"]
    address = context.user_data["address"]

    order_id = save_order(
        update.effective_user.id,
        name,
        phone,
        service,
        address,
        problem,
    )

    order_text = (
        "🔔 ЯНГИ БУЮРТМА!\n\n"
        f"🆔 Буюртма: #{order_id}\n"
        f"🔧 Хизмат: {service}\n"
        f"👤 Исм: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"📍 Манзил: {address}\n"
        f"📝 Муаммо: {problem}"
    )

    # Notify admin
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=order_text,
            )
        except Exception as e:
            logger.error("Admin notification error: %s", e)

    # Find workers
    workers = get_matching_workers(service)

    notified = 0

    for worker in workers:
        telegram_id = worker["telegram_id"]

        if not telegram_id:
            continue

        worker_text = (
            "🔔 СИЗГА ЯНГИ БУЮРТМА!\n\n"
            f"🔧 Хизмат: {service}\n"
            f"👤 Мижоз: {name}\n"
            f"📞 Телефон: {phone}\n"
            f"📍 Манзил: {address}\n"
            f"📝 Муаммо: {problem}\n\n"
            "Мижоз билан боғланишингиз мумкин."
        )

        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=worker_text,
            )
            notified += 1
        except Exception as e:
            logger.error(
                "Worker notification error: %s",
                e,
            )

    if notified:
        result_text = (
            "✅ Буюртмангиз қабул қилинди!\n\n"
            f"👨‍🔧 {notified} та мос устага хабар берилди."
        )
    else:
        result_text = (
            "✅ Буюртмангиз қабул қилинди!\n\n"
            "Ҳозирча мос устага Telegram орқали "
            "хабар бериш имкони бўлмади.\n"
            "Администратор сиз билан боғланади."
        )

    await update.message.reply_text(
        result_text,
        reply_markup=main_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


# =========================
# WORKER REGISTRATION
# =========================

async def worker_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "👨‍🔧 Уста чақириш бўлими\n\n"
        "Уста сифатида рўйхатдан ўтиб, "
        "буюртмалар олишингиз мумкин.",
        reply_markup=worker_keyboard(),
    )


async def worker_register_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.clear()

    await update.message.reply_text(
        "👤 Исм ва фамили
