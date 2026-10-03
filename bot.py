import logging
import os
import sqlite3
import unicodedata

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
    MessageHandler,
    ConversationHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

# Мижоз буюртмаси
NAME, PHONE, ADDRESS, PROBLEM = range(4)

# Уста рўйхатдан ўтиши
WORKER_NAME, WORKER_PHONE, WORKER_SERVICE, WORKER_AREA, WORKER_PRICE = range(5, 10)

# Эълон бериш
ANNOUNCEMENT_NAME, ANNOUNCEMENT_PHONE, ANNOUNCEMENT_SERVICE, ANNOUNCEMENT_ADDRESS, ANNOUNCEMENT_BUDGET, ANNOUNCEMENT_DETAILS = range(10, 16)

CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
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
        "х": "h",
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
        "ҳ": "h",
        "ў": "o",
        "ң": "ng",
    }
)


def get_database_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    connection = get_database_connection()

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                service TEXT NOT NULL,
                area TEXT NOT NULL,
                price TEXT NOT NULL,
                telegram_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                problem TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                service TEXT NOT NULL,
                address TEXT NOT NULL,
                budget TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Эски база бўлса, telegram_id устунини қўшиш
        worker_columns = connection.execute(
            "PRAGMA table_info(workers)"
        ).fetchall()

        column_names = {
            column["name"]
            for column in worker_columns
        }

        if "telegram_id" not in column_names:
            connection.execute(
                "ALTER TABLE workers ADD COLUMN telegram_id INTEGER"
            )

        connection.commit()

    finally:
        connection.close()


def save_order(
    service: str,
    name: str,
    phone: str,
    address: str,
    problem: str,
) -> None:
    connection = get_database_connection()

    try:
        connection.execute(
            """
            INSERT INTO orders (
                service,
                name,
                phone,
                address,
                problem
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                service,
                name,
                phone,
                address,
                problem,
            ),
        )

        connection.commit()

    finally:
        connection.close()


def save_worker(
    name: str,
    phone: str,
    service: str,
    area: str,
    price: str,
    telegram_id: int | None,
) -> None:
    connection = get_database_connection()

    try:
        existing = connection.execute(
            """
            SELECT id
            FROM workers
            WHERE phone = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (phone,),
        ).fetchone()

        if existing:
            connection.execute(
                """
                UPDATE workers
                SET
                    name = ?,
                    service = ?,
                    area = ?,
                    price = ?,
                    telegram_id = ?
                WHERE id = ?
                """,
                (
                    name,
                    service,
                    area,
                    price,
                    telegram_id,
                    existing["id"],
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO workers (
                    name,
                    phone,
                    service,
                    area,
                    price,
                    telegram_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    phone,
                    service,
                    area,
                    price,
                    telegram_id,
                ),
            )

        connection.commit()

    finally:
        connection.close()


def save_announcement(
    name: str,
    phone: str,
    service: str,
    address: str,
    budget: str,
    details: str,
) -> None:
    connection = get_database_connection()

    try:
        connection.execute(
            """
            INSERT INTO announcements (
                name,
                phone,
                service,
                address,
                budget,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                phone,
                service,
                address,
                budget,
                details,
            ),
        )

        connection.commit()

    finally:
        connection.close()


def get_workers() -> list[sqlite3.Row]:
    connection = get_database_connection()

    try:
        return connection.execute(
            """
            SELECT
                name,
                phone,
                service,
                area,
                price,
                telegram_id,
                created_at
            FROM workers
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        connection.close()


def get_orders() -> list[sqlite3.Row]:
    connection = get_database_connection()

    try:
        return connection.execute(
            """
            SELECT
                service,
                name,
                phone,
                address,
                problem,
                created_at
            FROM orders
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        connection.close()


def get_announcements() -> list[sqlite3.Row]:
    connection = get_database_connection()

    try:
        return connection.execute(
            """
            SELECT
                name,
                phone,
                service,
                address,
                budget,
                details,
                created_at
            FROM announcements
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        connection.close()


def get_statistics() -> dict[str, int]:
    connection = get_database_connection()

    try:
        return {
            "workers": connection.execute(
                "SELECT COUNT(*) FROM workers"
            ).fetchone()[0],

            "announcements": connection.execute(
                "SELECT COUNT(*) FROM announcements"
            ).fetchone()[0],

            "orders": connection.execute(
                "SELECT COUNT(*) FROM orders"
            ).fetchone()[0],
        }

    finally:
        connection.close()


def normalize_service_name(service: str) -> str:
    normalized = service.casefold()

    normalized = "".join(
        character
        for character in normalized
        if character != "\ufe0f"
        and not unicodedata.category(character).startswith(
            ("So", "Sk")
        )
    )

    normalized = " ".join(normalized.split())

    return normalized.translate(CYRILLIC_TO_LATIN)


def get_matching_workers(
    service: str,
) -> list[sqlite3.Row]:

    requested_service = normalize_service_name(service)

    connection = get_database_connection()

    try:
        workers = connection.execute(
            """
            SELECT
                name,
                service,
                area,
                price,
                phone,
                telegram_id
            FROM workers
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        connection.close()

    return [
        worker
        for worker in workers
        if normalize_service_name(
            worker["service"]
        ) == requested_service
    ]


def format_matching_workers(
    service: str,
    workers: list[sqlite3.Row],
) -> str:

    if not workers:
        return (
            "😔 Ҳозирча бу хизмат бўйича "
            "рўйхатдан ўтган уста топилмади."
        )

    service_name = normalize_service_name(service)

    records = [
        (
            f"#{index} {display_value(worker['name'])}\n"
            f"🔧 {display_value(worker['service'] or service_name)}\n"
            f"📍 {display_value(worker['area'])}\n"
            f"💰 {display_value(worker['price'])}\n"
            f"📞 {display_value(worker['phone'])}"
        )
        for index, worker in enumerate(
            workers,
            start=1,
        )
    ]

    return (
        "👨‍🔧 Мос усталар:\n\n"
        + "\n\n".join(records)
    )


# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    keyboard = [
        ["🔧 Хизматлар", "👨‍🔧 Уста чақириш"],
        ["📢 Эълон бериш", "📞 Алоқа"],
    ]

    if update.message:
        await update.message.reply_text(
            "🛠 Osh Service ботга хуш келибсиз!\n\n"
            "Керакли хизматни танланг:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard,
                resize_keyboard=True,
            ),
        )


# =========================
# ХИЗМАТЛАР
# =========================

async def services(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    keyboard = [
        ["🔧 Сантехник", "⚡ Электрик"],
        ["📱 Телефон таъмири", "💻 Компьютер таъмири"],
        ["🧹 Уй тозалаш", "🪑 Мебель таъмири"],
        ["⬅️ Орқага"],
    ]

    await update.message.reply_text(
        "🔧 Қайси хизмат керак?",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
        ),
    )


async def service_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    service = update.message.text

    if service == "⬅️ Орқага":
        await start(update, context)
        return ConversationHandler.END

    context.user_data["service"] = service

    matching_workers = get_matching_workers(
        service
    )

    for matching_message in split_message(
        format_matching_workers(
            service,
            matching_workers,
        )
    ):
        await update.message.reply_text(
            matching_message
        )

    await update.message.reply_text(
        f"Танланган хизмат: {service}\n\n"
        "👤 Исмингизни ёзинг:"
    )

    return NAME


async def get_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["name"] = update.message.text

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return PHONE


async def get_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["phone"] = update.message.text

    await update.message.reply_text(
        "📍 Манзилингизни ёзинг:"
    )

    return ADDRESS


async def get_address(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["address"] = update.message.text

    await update.message.reply_text(
        "📝 Муаммони ёки сизга керак бўлган "
        "хизматни ёзинг:"
    )

    return PROBLEM


async def get_problem(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["problem"] = update.message.text

    service = context.user_data["service"]
    name = context.user_data["name"]
    phone = context.user_data["phone"]
    address = context.user_data["address"]
    problem = context.user_data["problem"]

    save_order(
        service=service,
        name=name,
        phone=phone,
        address=address,
        problem=problem,
    )

    admin_message = (
        "🔔 ЯНГИ БУЮРТМА!\n\n"
        f"🔧 Хизмат: {service}\n"
        f"👤 Исм: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"📍 Манзил: {address}\n"
        f"📝 Муаммо: {problem}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_message,
    )

    matching_workers = get_matching_workers(
        service
    )

    notified_workers = 0

    worker_message = (
        "🔔 СИЗГА ЯНГИ БУЮРТМА!\n\n"
        f"🔧 Хизмат: {service}\n"
        f"👤 Мижоз: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"📍 Манзил: {address}\n"
        f"📝 Муаммо: {problem}\n\n"
        "Мижоз билан телефон орқали боғланишингиз мумкин."
    )

    for worker in matching_workers:

        telegram_id = worker["telegram_id"]

        if not telegram_id:
            continue

        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=worker_message,
            )

            notified_workers += 1

        except Exception:
            logging.exception(
                "Устага хабар юборишда хато: %s",
                telegram_id,
            )

    if notified_workers > 0:

        await update.message.reply_text(
            "✅ Буюртмангиз қабул қилинди!\n\n"
            f"👨‍🔧 {notified_workers} та мос устага "
            "буюртма ҳақида хабар берилди."
        )

    else:

        await update.message.reply_text(
            "✅ Буюртмангиз қабул қилинди!\n\n"
            "Ҳозирча мос устага Telegram орқали "
            "хабар бериш имкони бўлмади.\n"
            "Администратор сиз билан боғланади."
        )

    context.user_data.clear()

    await start(update, context)

    return ConversationHandler.END


# =========================
# УСТА
# =========================

async def worker_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    keyboard = [
        ["👨‍🔧 Уста бўлиб рўйхатдан ўтиш"],
        ["⬅️ Орқага"],
    ]

    await update.message.reply_text(
        "👨‍🔧 Уста чақириш бўлими\n\n"
        "Агар сиз хизмат кўрсатувчи уста бўлсангиз, "
        "бот орқали рўйхатдан ўтишингиз мумкин.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
        ),
    )


async def worker_register(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.message.text == "⬅️ Орқага":
        await start(update, context)
        return ConversationHandler.END

    await update.message.reply_text(
        "👤 Исмингиз ва фамилиянгизни ёзинг:"
    )

    return WORKER_NAME


async def get_worker_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["worker_name"] = update.message.text

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return WORKER_PHONE


async def get_worker_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["worker_phone"] = update.message.text

    await update.message.reply_text(
        "🔧 Қайси хизматни қиласиз?\n\n"
        "Масалан: сантехник, электрик, "
        "телефон таъмири"
    )

    return WORKER_SERVICE


async def get_worker_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["worker_service"] = update.message.text

    await update.message.reply_text(
        "📍 Қайси ҳудудда ишлайсиз?\n\n"
        "Масалан: Ош шаҳри, Навои кўчаси атрофи"
    )

    return WORKER_AREA


async def get_worker_area(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["worker_area"] = update.message.text

    await update.message.reply_text(
        "💰 Хизмат нархингизни ёзинг.\n\n"
        "Масалан: 500 сомдан бошланади"
    )

    return WORKER_PRICE


async def get_worker_price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["worker_price"] = update.message.text

    name = context.user_data["worker_name"]
    phone = context.user_data["worker_phone"]
    service = context.user_data["worker_service"]
    area = context.user_data["worker_area"]
    price = context.user_data["worker_price"]

    telegram_id = update.effective_user.id

    save_worker(
        name=name,
        phone=phone,
        service=service,
        area=area,
        price=price,
        telegram_id=telegram_id,
    )

    admin_message = (
        "👨‍🔧 ЯНГИ УСТА РЎЙХАТДАН ЎТМОҚДА!\n\n"
        f"👤 Исм: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"🔧 Хизмат: {service}\n"
        f"📍 Ҳудуд: {area}\n"
        f"💰 Нарх: {price}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_message,
    )

    await update.message.reply_text(
        "✅ Маълумотларингиз қабул қилинди!\n\n"
        "Администратор маълумотларни текширади.\n\n"
        "📲 Telegram ID ҳам сақланди. "
        "Кейин мос буюртма келганда сизга "
        "Telegram орқали хабар юборилади."
    )

    context.user_data.clear()

    await start(update, context)

    return ConversationHandler.END


# =========================
# ЭЪЛОН
# =========================

async def announcement_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "📢 Эълон бериш\n\n"
        "Аввало исмингизни ёзинг:"
    )

    return ANNOUNCEMENT_NAME


async def get_announcement_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["announcement_name"] = update.message.text

    await update.message.reply_text(
        "📞 Телефон рақамингизни ёзинг:"
    )

    return ANNOUNCEMENT_PHONE


async def get_announcement_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["announcement_phone"] = update.message.text

    await update.message.reply_text(
        "🔧 Сизга қайси хизмат керак?"
    )

    return ANNOUNCEMENT_SERVICE


async def get_announcement_service(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["announcement_service"] = update.message.text

    await update.message.reply_text(
        "📍 Манзилингизни ёзинг:"
    )

    return ANNOUNCEMENT_ADDRESS


async def get_announcement_address(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["announcement_address"] = update.message.text

    await update.message.reply_text(
        "💰 Бюджетингизни ёзинг:"
    )

    return ANNOUNCEMENT_BUDGET


async def get_announcement_budget(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["announcement_budget"] = update.message.text

    await update.message.reply_text(
        "📝 Эълонингиз ҳақида батафсил маълумот ёзинг:"
    )

    return ANNOUNCEMENT_DETAILS


async def get_announcement_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["announcement_details"] = update.message.text

    name = context.user_data["announcement_name"]
    phone = context.user_data["announcement_phone"]
    service = context.user_data["announcement_service"]
    address = context.user_data["announcement_address"]
    budget = context.user_data["announcement_budget"]
    details = context.user_data["announcement_details"]

    save_announcement(
        name=name,
        phone=phone,
        service=service,
        address=address,
        budget=budget,
        details=details,
    )

    admin_message = (
        "📢 ЯНГИ ЭЪЛОН!\n\n"
        f"👤 Исм: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"🔧 Керакли хизмат: {service}\n"
        f"📍 Манзил: {address}\n"
        f"💰 Бюджет: {budget}\n"
        f"📝 Батафсил маълумот: {details}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_message,
    )

    await update.message.reply_text(
        "✅ Эълонингиз қабул қилинди!\n\n"
        "Администратор маълумотларни кўриб чиқади "
        "ва сиз билан боғланади."
    )

    context.user_data.clear()

    await start(update, context)

    return ConversationHandler.END


# =========================
# ЁРДАМ
# =========================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "Менюдан керакли хизматни танланг."
    )


# =========================
# ADMIN
# =========================

def is_admin(update: Update) -> bool:

    user = update.effective_user

    return (
        user is not None
        and user.id == ADMIN_ID
    )


def admin_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👨‍🔧 Усталар",
                    callback_data="admin:workers",
                ),
                InlineKeyboardButton(
                    "📢 Эълонлар",
                    callback_data="admin:announcements",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔔 Буюртмалар",
                    callback_data="admin:orders",
                ),
                InlineKeyboardButton(
                    "📊 Статистика",
                    callback_data="admin:stats",
                ),
            ],
        ]
    )


def admin_back_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Админ меню",
                    callback_data="admin:back",
                )
            ]
        ]
    )


def display_value(
    value: object,
    limit: int = 500,
) -> str:

    text = str(value)

    if len(text) <= limit:
        return text

    return f"{text[:limit - 1]}…"


def split_message(
    text: str,
    max_length: int = 3500,
) -> list[str]:

    chunks: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in text.splitlines():

        line_length = len(line) + 1

        if (
            current_lines
            and current_length + line_length > max_length
        ):
            chunks.append(
                "\n".join(current_lines)
            )

            current_lines = []
            current_length = 0

        current_lines.append(line)
        current_length += line_length

    if current_lines:
        chunks.append(
            "\n".join(current_lines)
        )

    return chunks or [text]


def format_workers() -> str:

    workers = get_workers()

    if not workers:
        return (
            "👨‍🔧 Усталар\n\n"
            "Ҳозирча рўйхатдан ўтган усталар йўқ."
        )

    records = [
        (
            f"#{index}\n"
            f"👤 Исм: {display_value(worker['name'])}\n"
            f"📞 Телефон: {display_value(worker['phone'])}\n"
            f"🔧 Хизмат: {display_value(worker['service'])}\n"
            f"📍 Ҳудуд: {display_value(worker['area'])}\n"
            f"💰 Нарх: {display_value(worker['price'])}\n"
            f"🕒 Сана: {display_value(worker['created_at'])}"
        )
        for index, worker in enumerate(
            workers,
            start=1,
        )
    ]

    return (
        f"👨‍🔧 Усталар\n\n"
        f"Жами: {len(workers)}\n\n"
        + "\n\n".join(records)
    )


def format_announcements() -> str:

    announcements = get_announcements()

    if not announcements:
        return (
            "📢 Эълонлар\n\n"
            "Ҳозирча эълонлар йўқ."
        )

    records = [
        (
            f"#{index}\n"
            f"👤 Исм: {display_value(announcement['name'])}\n"
            f"📞 Телефон: {display_value(announcement['phone'])}\n"
            f"🔧 Хизмат: {display_value(announcement['service'])}\n"
            f"📍 Манзил: {display_value(announcement['address'])}\n"
            f"💰 Бюджет: {display_value(announcement['budget'])}\n"
            f"📝 Тафсилот: {display_value(announcement['details'])}\n"
            f"🕒 Сана: {display_value(announcement['created_at'])}"
        )
        for index, announcement in enumerate(
            announcements,
            start=1,
        )
    ]

    return (
        f"📢 Эълонлар\n\n"
        f"Жами: {len(announcements)}\n\n"
        + "\n\n".join(records)
    )


def format_orders() -> str:

    orders = get_orders()

    if not orders:
        return (
            "🔔 Буюртмалар\n\n"
            "Ҳозирча буюртмалар йўқ."
        )

    records = [
        (
            f"#{index}\n"
            f"🔧 Хизмат: {display_value(order['service'])}\n"
            f"👤 Исм: {display_value(order['name'])}\n"
            f"📞 Телефон: {display_value(order['phone'])}\n"
            f"📍 Манзил: {display_value(order['address'])}\n"
            f"📝 Муаммо: {display_value(order['problem'])}\n"
            f"🕒 Сана: {display_value(order['created_at'])}"
        )
        for index, order in enumerate(
            orders,
            start=1,
        )
    ]

    return (
        f"🔔 Буюртмалар\n\n"
        f"Жами: {len(orders)}\n\n"
        + "\n\n".join(records)
    )


def format_statistics() -> str:

    statistics = get_statistics()

    total = (
        statistics["workers"]
        + statistics["announcements"]
        + statistics["orders"]
    )

    return (
        "📊 Статистика\n\n"
        f"👨‍🔧 Усталар: {statistics['workers']}\n"
        f"📢 Эълонлар: {statistics['announcements']}\n"
        f"🔔 Буюртмалар: {statistics['orders']}\n"
        f"\nЖами ёзувлар: {total}"
    )


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(update):

        await update.message.reply_text(
            "⛔ Сизда админ панелидан "
            "фойдаланиш ҳуқуқи йўқ."
        )

        return

    await update.message.reply_text(
        "🔐 Админ панели\n\n"
        "Керакли бўлимни танланг:",
        reply_markup=admin_keyboard(),
    )


async def admin_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:

        await query.edit_message_text(
            "⛔ Сизда админ панелидан "
            "фойдаланиш ҳуқуқи йўқ."
        )

        return

    if query.data == "admin:back":

        await query.edit_message_text(
            "🔐 Админ панели\n\n"
            "Керакли бўлимни танланг:",
            reply_markup=admin_keyboard(),
        )

        return

    section_formatters = {
        "admin:workers": format_workers,
        "admin:announcements": format_announcements,
        "admin:orders": format_orders,
        "admin:stats": format_statistics,
    }

    formatter = section_formatters.get(
        query.data
    )

    if formatter is None:

        await query.edit_message_text(
            "⚠️ Номаълум админ панели бўлими.",
            reply_markup=admin_keyboard(),
        )

        return

    messages = split_message(
        formatter()
    )

    await query.edit_message_text(
        messages[0],
        reply_markup=admin_back_keyboard(),
    )

    if query.message is not None:

        for message in messages[1:]:

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=message,
            )


# =========================
# МЕНЮ
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = update.message.text

    if text == "🔧 Хизматлар":

        await services(
            update,
            context,
        )

    elif text == "👨‍🔧 Уста чақириш":

        await worker_start(
            update,
            context,
        )

    elif text == "📢 Эълон бериш":

        await announcement_start(
            update,
            context,
        )

    elif text == "📞 Алоқа":

        await update.message.reply_text(
            "📞 Администратор билан боғланиш учун "
            "хизмат буюртмасини қолдиринг."
        )

    else:

        await update.message.reply_text(
            "Илтимос, менюдаги тугмалардан "
            "бирини танланг."
        )


# =========================
# APPLICATION
# =========================

def create_application() -> Application:

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN топилмади."
        )

    if ADMIN_ID <= 0:
        raise RuntimeError(
            "ADMIN_ID топилмади."
        )

    initialize_database()

    application = (
        Application.builder()
        .token(token)
        .build()
    )

    # Мижоз буюртмаси
    order_conversation = ConversationHandler(

        entry_points=[
            MessageHandler(
                filters.Regex(
                    "^(🔧 Сантехник|⚡ Электрик|📱 Телефон таъмири|"
                    "💻 Компьютер таъмири|🧹 Уй тозалаш|🪑 Мебель таъмири)$"
                ),
                service_selected,
            )
        ],

        states={

            NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_name,
                )
            ],

            PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_phone,
                )
            ],

            ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_address,
                )
            ],

            PROBLEM: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_problem,
                )
            ],
        },

        fallbacks=[],
    )

    # Уста
    worker_conversation = ConversationHandler(

        entry_points=[
            MessageHandler(
                filters.Regex(
                    "^👨‍🔧 Уста бўлиб рўйхатдан ўтиш$"
                ),
                worker_register,
            )
        ],

        states={

            WORKER_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_worker_name,
                )
            ],

            WORKER_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_worker_phone,
                )
            ],

            WORKER_SERVICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_worker_service,
                )
            ],

            WORKER_AREA: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_worker_area,
                )
            ],

            WORKER_PRICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_worker_price,
                )
            ],
        },

        fallbacks=[],
    )

    # Эълон
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

            ANNOUNCEMENT_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_announcement_name,
                )
            ],

            ANNOUNCEMENT_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_announcement_phone,
                )
            ],

            ANNOUNCEMENT_SERVICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_announcement_service,
                )
            ],

            ANNOUNCEMENT_ADDRESS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_announcement_address,
                )
            ],

            ANNOUNCEMENT_BUDGET: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_announcement_budget,
                )
            ],

            ANNOUNCEMENT_DETAILS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_announcement_details,
                )
            ],
        },

        fallbacks=[],
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    application.add_handler(
        order_conversation
    )

    application.add_handler(
        worker_conversation
    )

    application.add_handler(
        announcement_conversation
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_button,
            pattern="^admin:",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    return application


# =========================
# RENDER + TELEGRAM WEBHOOK
# =========================

def main():

    application = create_application()

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    render_url = os.getenv(
        "RENDER_EXTERNAL_URL"
    )

    if not render_url:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL топилмади."
        )

    webhook_url = (
        render_url.rstrip("/")
        + "/telegram"
    )

    logging.info(
        "Telegram webhook: %s",
        webhook_url,
    )

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram",
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
