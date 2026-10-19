import os
import re
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import psycopg

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
PORT = int(os.getenv('PORT', '10000'))
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')
MBANK_PAYMENT_DETAILS = os.getenv(
    'MBANK_PAYMENT_DETAILS',
    'MBANK реквизити ҳали киритилмаган. Администратор билан боғланинг.'
)

if not BOT_TOKEN:
    raise RuntimeError('TELEGRAM_BOT_TOKEN топилмади')
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL топилмади')

FREE_ORDER_LIMIT = 7
FREE_ANNOUNCEMENT_LIMIT = 7
SUBSCRIPTION_PRICE = Decimal("19990.00")
SUBSCRIPTION_CURRENCY = "UZS"
SUBSCRIPTION_DAYS = 30

COUNTRIES = {
    '🇰🇬 Қирғизистон': {
        'code': 'KG', 'currency': 'сом',
        'cities': ['Ош', 'Бишкек', 'Жалал-Абад', 'Каракол', 'Токмок']
    },
    '🇺🇿 Ўзбекистон': {
        'code': 'UZ', 'currency': 'сўм',
        'cities': ['Тошкент', 'Самарқанд', 'Андижон', 'Наманган', 'Фарғона', 'Бухоро', 'Қарши', 'Нукус']
    },
}
COUNTRY_BY_CODE = {'KG': '🇰🇬 Қирғизистон', 'UZ': '🇺🇿 Ўзбекистон'}
CITY_COUNTRY = {
    'osh': 'KG', 'bishkek': 'KG', 'jalalabad': 'KG', 'karakol': 'KG', 'tokmok': 'KG',
    'toshkent': 'UZ', 'samarqand': 'UZ', 'andijon': 'UZ', 'namangan': 'UZ',
    'fargona': 'UZ', 'buxoro': 'UZ', 'qarshi': 'UZ', 'nukus': 'UZ'
}
SERVICES = [
    # Мавжуд хизматлар
    '🔧 Сантехник', '⚡ Электрик', '📱 Телефон таъмири',
    '💻 Компьютер таъмири', '🧹 Уй тозалаш', '🪑 Мебель таъмири',
    # Қўшимча 20 та хизмат
    '🧱 Қурувчи', '🎨 Маляр — бўёқчи', '🧱 Плитка териш устаси',
    '🪚 Дурадгор', '🔑 Қулф таъмирлаш устаси', '❄️ Кондиционер ўрнатиш ва таъмирлаш',
    '🧺 Кир ювиш машинаси таъмири', '🧊 Музлатгич таъмири', '🚗 Автомобиль устаси',
    '🚿 Душ ва ванна ўрнатиш', '🪟 Эшик ва дераза ўрнатиш', '📡 Интернет ва Wi-Fi созлаш',
    '📹 Видеокузатув камераси ўрнатиш', '🚚 Юк ташиш хизмати', '🌳 Боғбон ва ҳовли тозалаш',
    '💇 Сартарош хизмати', '💄 Соч турмаклаш ва макияж', '🧑‍🏫 Репетитор хизмати',
    '🧵 Тикувчилик', '🐜 Ҳашаротларга қарши кураш', '🧰 Кунлик ишчи'
]
SERVICE_PATTERN = r'^(?:' + '|'.join(re.escape(x) for x in SERVICES) + r')$'
ANNOUNCEMENT_TYPES = ['🛒 Сотаман', '🛍 Сотиб оламан', '🏠 Ижарага бераман', '🔑 Ижарага оламан', '📢 Бошқа эълон']
ANNOUNCEMENT_TYPE_PATTERN = r'^(?:' + '|'.join(re.escape(x) for x in ANNOUNCEMENT_TYPES) + r')$'

BACK_MENU_PATTERN = r'^⬅️ Бош меню$'
BACK_MENU_FILTER = filters.Regex(BACK_MENU_PATTERN)

EDIT_INPUT_FILTER = (
    filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN) &
    ~filters.Regex(r'^(?:👤 Менинг профилим|👨‍🔧 Устаман|👨‍🔧 Уста бўлиб рўйхатдан ўтиш|📢 Эълон бериш|🔧 Хизматлар|Алоқа|🌍 Давлат/шаҳар|⬅️ Бош меню)$')
)

WORKER_COUNTRY, WORKER_CITY, WORKER_NAME, WORKER_PHONE, WORKER_SERVICE, WORKER_AREA, WORKER_PRICE = range(7)
ORDER_SERVICE, ORDER_NAME, ORDER_PHONE, ORDER_ADDRESS, ORDER_PROBLEM = range(10, 15)
ANN_COUNTRY, ANN_CITY, ANN_NAME, ANN_PHONE, ANN_SERVICE, ANN_ADDRESS, ANN_BUDGET, ANN_DETAILS = range(20, 28)
LOCATION_COUNTRY, LOCATION_CITY = range(40, 42)
EDIT_COUNTRY, EDIT_CITY, EDIT_NAME, EDIT_PHONE, EDIT_SERVICE, EDIT_AREA, EDIT_PRICE = range(50, 57)
FEEDBACK_TEXT = 60


def get_connection():
    return psycopg.connect(DATABASE_URL)


def normalize_text(text):
    if not text:
        return ''
    s = str(text).casefold().strip()
    s = s.replace('’', "'").replace('ʻ', "'").replace('ʼ', "'").replace('`', "'").replace('´', "'")
    s = s.translate(str.maketrans({
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'j','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'x','ц':'ts','ч':'ch','ш':'sh','щ':'sh','ъ':'','ы':'i','ь':'','э':'e','ю':'yu','я':'ya','қ':'q','ғ':'g','ҳ':'h','ў':'o','ң':'ng','ө':'o','ү':'u','җ':'j'
    }))
    s = re.sub(r"[^\w\s']", ' ', s, flags=re.UNICODE).replace("'", '')
    return re.sub(r'\s+', ' ', s).strip()


def canonical_country(text):
    s = normalize_text(text)
    if not s:
        return ''
    aliases = {
        'kg':'KG','kyrgyzstan':'KG','kyrgyz':'KG','kirgizistan':'KG','qirgiziston':'KG','qirgiz':'KG',
        'uz':'UZ','uzbekistan':'UZ','uzbekiston':'UZ','uzbek':'UZ','ozbekiston':'UZ','ozbek':'UZ'
    }
    if s in aliases:
        return aliases[s]
    if 'qirgiz' in s or 'kyrgyz' in s or 'kirgiz' in s:
        return 'KG'
    if 'uzbek' in s or 'ozbek' in s:
        return 'UZ'
    return ''


def canonical_city(text):
    s = normalize_text(text).replace(' ', '')
    if not s:
        return ''
    for suffix in ('shahri', 'shahar', 'city', 'gorod', 'shaary', 'shaar'):
        s = s.replace(suffix, '')
    aliases = {
        'osh':'osh','oshshaary':'osh','oshshaar':'osh','bishkek':'bishkek',
        'jalalabad':'jalalabad','jallalabad':'jalalabad','jalalabat':'jalalabad','dzhalalabad':'jalalabad',
        'karakol':'karakol','tokmok':'tokmok','toshkent':'toshkent','tashkent':'toshkent',
        'samarqand':'samarqand','samarkand':'samarqand','andijon':'andijon','andijan':'andijon',
        'namangan':'namangan','fargona':'fargona','fergana':'fargona','buxoro':'buxoro',
        'bukhara':'buxoro','qarshi':'qarshi','karshi':'qarshi','nukus':'nukus'
    }
    return aliases.get(s, s)


def canonical_service(text):
    s = normalize_text(text)
    if not s:
        return ''
    aliases = {
        'elektrik':['elektrik','elektr','elektrchi','electric','electrician','elektirik','svet','svetchi','svetchik','light','osvetlenie','yoritish','yoruglik','yorug','tok','tokchi','sim','simchi','provod','provodka','elektrmontaj','elektromontaj'],
        'santexnik':['santexnik','santehnik','santexnikchi','santehnikchi','santex','vodoprovod','vodoprovodchi','kran','kranchi','suv','suuvchi','kanalizatsiya','truba','trubachi','ariston','unitaz','rakovina','dush'],
        'telefon':['telefon','telefonchi','telefonremont','phone','iphone','samsung','xiaomi','redmi','oppo','vivo','honor','smartphone'],
        'kompyuter':['kompyuter','komputer','komyuter','kompyuterchi','komputerchi','noutbuk','notebook','laptop','printer','windows','sistemnik'],
        'tozalash':['tozalash','uytozalash','tozalovchi','uborka','uborshik','uborshitsa','cleaning','cleaner'],
        'mebel':['mebel','mebelchi','mebelremont','divan','shkaf','stol','stul','krovat','oshxona']
    }
    for key, vals in aliases.items():
        if s == key or any(v == s or v in s for v in vals):
            return key
    return s


def city_matches(a, b):
    return bool(canonical_city(a) and canonical_city(a) == canonical_city(b))


def service_matches(a, b):
    aa = {canonical_service(x) for x in re.split(r'[,;/|\n]+', str(a or '')) if canonical_service(x)}
    bb = {canonical_service(x) for x in re.split(r'[,;/|\n]+', str(b or '')) if canonical_service(x)}
    return bool(aa & bb)


def country_from_city(city):
    return CITY_COUNTRY.get(canonical_city(city), '')


def country_name(code):
    return COUNTRY_BY_CODE.get(code, '')


def currency(code):
    return 'сом' if code == 'KG' else 'сўм' if code == 'UZ' else ''


def display_city(city):
    names = {
        'osh':'Ош','bishkek':'Бишкек','jalalabad':'Жалал-Абад','karakol':'Каракол','tokmok':'Токмок',
        'toshkent':'Тошкент','samarqand':'Самарқанд','andijon':'Андижон','namangan':'Наманган',
        'fargona':'Фарғона','buxoro':'Бухоро','qarshi':'Қарши','nukus':'Нукус'
    }
    return names.get(canonical_city(city), city or '')


def infer_worker_location(country_code, country_name_value, city, area):
    code = canonical_country(country_code) or canonical_country(country_name_value) or country_from_city(city) or country_from_city(area)
    fixed_city = city or ''
    if not canonical_city(fixed_city):
        fixed_city = area or ''
    return code, country_name(code) or country_name_value or '', display_city(fixed_city), currency(code)


def init_database():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS user_profiles (telegram_id BIGINT PRIMARY KEY,country_code TEXT,country_name TEXT,city TEXT,currency TEXT,created_at TIMESTAMPTZ DEFAULT NOW(),updated_at TIMESTAMPTZ DEFAULT NOW())''')
            cur.execute('''CREATE TABLE IF NOT EXISTS bot_users (telegram_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, first_seen TIMESTAMPTZ DEFAULT NOW(), last_seen TIMESTAMPTZ DEFAULT NOW())''')
            cur.execute('''CREATE TABLE IF NOT EXISTS workers (id SERIAL PRIMARY KEY,telegram_id BIGINT,name TEXT,phone TEXT,service TEXT,area TEXT,price TEXT,created_at TIMESTAMPTZ DEFAULT NOW())''')
            for c, d in [
                ('is_active','BOOLEAN DEFAULT TRUE'), ('is_blocked','BOOLEAN DEFAULT FALSE'), ('country_code','TEXT'), ('country_name','TEXT'),
                ('city','TEXT'), ('currency','TEXT'), ('free_orders_used','INTEGER DEFAULT 0'),
                ('subscription_until','TIMESTAMPTZ'), ('payment_pending','BOOLEAN DEFAULT FALSE')
            ]:
                cur.execute(f'ALTER TABLE workers ADD COLUMN IF NOT EXISTS {c} {d}')
            cur.execute('''CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY,telegram_id BIGINT,name TEXT,phone TEXT,service TEXT,address TEXT,problem TEXT,created_at TIMESTAMPTZ DEFAULT NOW())''')
            for c, d in [
                ('status',"TEXT DEFAULT 'new'"), ('accepted_worker_id','INTEGER'), ('accepted_worker_name','TEXT'),
                ('accepted_at','TIMESTAMPTZ'), ('country_code','TEXT'), ('country_name','TEXT'),
                ('city','TEXT'), ('currency','TEXT')
            ]:
                cur.execute(f'ALTER TABLE orders ADD COLUMN IF NOT EXISTS {c} {d}')
            cur.execute('''CREATE TABLE IF NOT EXISTS announcements (id SERIAL PRIMARY KEY,telegram_id BIGINT,name TEXT,phone TEXT,service TEXT,address TEXT,budget TEXT,details TEXT,created_at TIMESTAMPTZ DEFAULT NOW())''')
            for c, d in [('country_code','TEXT'),('country_name','TEXT'),('city','TEXT'),('currency','TEXT')]:
                cur.execute(f'ALTER TABLE announcements ADD COLUMN IF NOT EXISTS {c} {d}')
            cur.execute('''CREATE TABLE IF NOT EXISTS user_subscriptions (
                telegram_id BIGINT PRIMARY KEY,
                subscription_until TIMESTAMPTZ,
                payment_pending BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS subscription_payments (
                id SERIAL PRIMARY KEY,
                worker_id INTEGER,
                telegram_id BIGINT NOT NULL,
                amount NUMERIC(10,2) NOT NULL DEFAULT 19990.00,
                currency TEXT NOT NULL DEFAULT 'UZS',
                subscription_type TEXT NOT NULL DEFAULT 'worker',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                reviewed_by BIGINT
            )''')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_workers_tg ON workers(telegram_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')
            cur.execute('ALTER TABLE subscription_payments ALTER COLUMN amount TYPE NUMERIC(10,2) USING amount::numeric')
            cur.execute('ALTER TABLE subscription_payments ALTER COLUMN amount SET DEFAULT 19990.00')
            cur.execute('ALTER TABLE subscription_payments ALTER COLUMN worker_id DROP NOT NULL')
            cur.execute("ALTER TABLE subscription_payments ADD COLUMN IF NOT EXISTS subscription_type TEXT NOT NULL DEFAULT 'worker'")
            cur.execute("ALTER TABLE subscription_payments ALTER COLUMN currency SET DEFAULT 'UZS'")
            cur.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON subscription_payments(status)')
            cur.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )''')
            cur.execute('''INSERT INTO bot_settings(setting_key, setting_value)
                           VALUES ('payment_details', %s)
                           ON CONFLICT (setting_key) DO NOTHING''', (MBANK_PAYMENT_DETAILS,))
        conn.commit()
    finally:
        conn.close()
    repair_old_workers()


def repair_old_workers():
    conn = get_connection()
    fixed = 0
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,country_code,country_name,city,area FROM workers')
            for wid, cc, cn, city, area in cur.fetchall():
                code, cname, cty, curr = infer_worker_location(cc, cn, city, area)
                if code or cty:
                    cur.execute('''UPDATE workers SET country_code=%s,country_name=%s,city=%s,currency=%s WHERE id=%s''', (code or cc, cname or cn, cty or city, curr or None, wid))
                    fixed += 1
        conn.commit()
        logger.info('Legacy worker repair completed: %s rows checked/updated', fixed)
    except Exception:
        conn.rollback()
        logger.exception('repair_old_workers failed')
    finally:
        conn.close()


def main_keyboard():
    return ReplyKeyboardMarkup([
        ['🔧 Хизматлар','👨‍🔧 Устаман'],
        ['📢 Эълон бериш','Алоқа'],
        ['💡 Таклиф юбориш','⚠️ Шикоят юбориш'],
        ['👤 Менинг профилим'],
        ['🌍 Давлат/шаҳар']
    ], resize_keyboard=True)


def service_keyboard(selected=None, multi=False):
    selected = set(selected or [])
    labels = []
    for i in range(0, len(SERVICES), 2):
        row = []
        for service in SERVICES[i:i + 2]:
            row.append((('☑️ ' if service in selected else '⬜ ') + service) if multi else service)
        labels.append(row)
    if multi:
        labels.append(['✅ Танловни тасдиқлаш'])
    labels.append(['⬅️ Бош меню'])
    return ReplyKeyboardMarkup(labels, resize_keyboard=True)


def announcement_type_keyboard():
    return ReplyKeyboardMarkup([
        ANNOUNCEMENT_TYPES[0:2], ANNOUNCEMENT_TYPES[2:4],
        ANNOUNCEMENT_TYPES[4:5], ['⬅️ Бош меню']
    ], resize_keyboard=True)


def parse_selected_services(value):
    # Convert stored comma-separated service names to known service labels.
    parts = [part.strip() for part in re.split(r'[,;/|\n]+', str(value or '')) if part.strip()]
    selected = []
    for service in SERVICES:
        if service in parts or any(canonical_service(part) == canonical_service(service) for part in parts):
            selected.append(service)
    return selected


def service_selection_prompt(selected=None):
    chosen = selected or []
    status = '\n'.join(f"{'☑️' if s in chosen else '⬜'} {s}" for s in SERVICES)
    return ('🔧 Қайси хизматларни кўрсатасиз?\n\n'
            'Бир нечта хизматни танлаш мумкин. Танланган тугмани яна босиб, танловдан чиқариш мумкин.\n\n'
            f'{status}\n\nТугатгач, «✅ Танловни тасдиқлаш»ни босинг.')


def country_keyboard():
    return ReplyKeyboardMarkup([['🇰🇬 Қирғизистон'],['🇺🇿 Ўзбекистон']], resize_keyboard=True)


def city_keyboard(country):
    cities = COUNTRIES[country]['cities']
    rows = [cities[i:i+2] for i in range(0, len(cities), 2)]
    rows += [['✏️ Бошқа шаҳар'],['⬅️ Бош меню']]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def worker_menu_keyboard():
    return ReplyKeyboardMarkup([
        ['👨‍🔧 Уста бўлиб рўйхатдан ўтиш'],
        ['👤 Менинг профилим'],
        ['⬅️ Бош меню']
    ], resize_keyboard=True)


def get_location(tg):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT country_code,country_name,city,currency FROM user_profiles WHERE telegram_id=%s', (tg,))
            r = cur.fetchone()
            return None if not r else dict(zip(['country_code','country_name','city','currency'], r))
    finally:
        conn.close()


def save_location(tg, code, name, city, curr):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO user_profiles(telegram_id,country_code,country_name,city,currency)
                           VALUES(%s,%s,%s,%s,%s)
                           ON CONFLICT(telegram_id) DO UPDATE SET
                           country_code=EXCLUDED.country_code,country_name=EXCLUDED.country_name,
                           city=EXCLUDED.city,currency=EXCLUDED.currency,updated_at=NOW()''',
                        (tg, code, name, city, curr))
        conn.commit()
    finally:
        conn.close()


def get_worker_subscription(telegram_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,COALESCE(free_orders_used,0),subscription_until,
                                  COALESCE(payment_pending,FALSE),is_active
                           FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1''', (telegram_id,))
            row = cur.fetchone()
            if not row:
                return None
            wid, free_used, subscription_until, payment_pending, active = row
            now = datetime.now(timezone.utc)
            subscribed = bool(subscription_until and subscription_until > now)
            return {
                'id': wid, 'free_orders_used': free_used, 'subscription_until': subscription_until,
                'payment_pending': payment_pending, 'subscribed': subscribed, 'active': active
            }
    finally:
        conn.close()


def subscription_text(sub):
    if not sub:
        return '❗ Уста профили топилмади.'
    if sub['subscribed']:
        until = sub['subscription_until'].astimezone().strftime('%d.%m.%Y %H:%M')
        return f'♾️ PRO обуна фаол.\n📅 Амал қилиш муддати: {until}'
    used = sub['free_orders_used']
    if used < FREE_ORDER_LIMIT:
        return f'🎁 Бепул буюртмалар: {used}/{FREE_ORDER_LIMIT}'
    return '🔒 7 та бепул буюртма тугаган. PRO обуна: 19 990 сўм / 30 кун.'


def get_payment_details():
    # Return admin-configured details, falling back to the Render environment variable.
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT setting_value FROM bot_settings WHERE setting_key='payment_details'")
            row = cur.fetchone()
            return row[0] if row and row[0] else MBANK_PAYMENT_DETAILS
    finally:
        conn.close()


def save_payment_details(value):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO bot_settings(setting_key, setting_value, updated_at)
                           VALUES ('payment_details', %s, NOW())
                           ON CONFLICT (setting_key) DO UPDATE
                           SET setting_value=EXCLUDED.setting_value, updated_at=NOW()''', (value,))
        conn.commit()
    finally:
        conn.close()


def payment_keyboard(subscription_type='worker'):
    prefix = 'ads' if subscription_type == 'ads' else 'worker'
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💳 Тўлов маълумоти', callback_data=f'payment:{prefix}_info')],
        [InlineKeyboardButton('✅ Тўладим', callback_data=f'payment:{prefix}_paid')]
    ])


async def send_payment_info(bot, chat_id, subscription_type='worker'):
    if subscription_type == 'ads':
        purpose = '📢 Эълон беришни давом эттириш'
        benefit = '📢 Эълонларни чексиз жойлаштириш'
    else:
        purpose = '👨‍🔧 Уста PRO обунаси'
        benefit = '♾️ Чексиз буюртма қабул қилиш'
    text = (
        f'💳 **TEZ Service — ойлик обуна**\n\n'
        f'{purpose}\n'
        f'💰 Нархи: 19 990 сўм / ой\n'
        f'📅 Муддати: {SUBSCRIPTION_DAYS} кун\n'
        f'{benefit}\n\n'
        f'🏦 Тўлов реквизити:\n{get_payment_details()}\n\n'
        f'Тўловни амалга оширгандан кейин «✅ Тўладим» тугмасини босинг ва чек расмини юборинг.'
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown', reply_markup=payment_keyboard(subscription_type))


async def payment_start(update, context):
    await send_payment_info(context.bot, update.effective_user.id, 'worker')


async def payment_callback(update, context):
    q = update.callback_query
    await q.answer()
    action = q.data.split(':', 1)[1]
    tg = q.from_user.id
    is_ads = action.startswith('ads_')
    subscription_type = 'ads' if is_ads else 'worker'
    sub = get_worker_subscription(tg) if not is_ads else None
    if not is_ads and not sub:
        await q.message.reply_text('❗ Аввало уста сифатида рўйхатдан ўтинг.')
        return
    if action.endswith('_info') or action == 'info':
        await send_payment_info(context.bot, tg, subscription_type)
        return
    if action.endswith('_paid') or action == 'paid':
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM subscription_payments WHERE telegram_id=%s AND subscription_type=%s AND status='pending' ORDER BY id DESC LIMIT 1", (tg, subscription_type))
                existing = cur.fetchone()
                if existing:
                    payment_id = existing[0]
                else:
                    cur.execute('''INSERT INTO subscription_payments(worker_id,telegram_id,amount,currency,subscription_type,status)
                                   VALUES(%s,%s,%s,%s,%s,'pending') RETURNING id''',
                                (sub['id'] if sub else None, tg, SUBSCRIPTION_PRICE, SUBSCRIPTION_CURRENCY, subscription_type))
                    payment_id = cur.fetchone()[0]
                if subscription_type == 'worker':
                    cur.execute('UPDATE workers SET payment_pending=TRUE WHERE id=%s', (sub['id'],))
                else:
                    cur.execute('''INSERT INTO user_subscriptions(telegram_id,payment_pending,updated_at) VALUES(%s,TRUE,NOW())
                                   ON CONFLICT(telegram_id) DO UPDATE SET payment_pending=TRUE,updated_at=NOW()''', (tg,))
            conn.commit()
        finally:
            conn.close()
        context.user_data['pending_payment_id'] = payment_id
        context.user_data['pending_payment_type'] = subscription_type
        await q.message.reply_text(
            f'✅ Тўлов сўрови очилди: #{payment_id}\n\n'
            '💰 Тўлов: 19 990 сўм\n'
            '📸 Тўлов чеки/скриншотини шу ерга расм қилиб юборинг.\n\n'
            '⚠️ Чекда карта рақамининг тўлиқ кўриниши ёки махфий маълумотлар бўлмасин. '
            'Администратор тўловни текширгандан кейингина обуна ёқилади.'
        )


async def payment_receipt_photo(update, context):
    if not update.effective_user or not update.message or not update.message.photo:
        return
    tg = update.effective_user.id
    payment_id = context.user_data.get('pending_payment_id')
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if payment_id:
                cur.execute("SELECT id,subscription_type FROM subscription_payments WHERE id=%s AND telegram_id=%s AND status='pending'", (payment_id, tg))
            else:
                cur.execute("SELECT id,subscription_type FROM subscription_payments WHERE telegram_id=%s AND status='pending' ORDER BY id DESC LIMIT 1", (tg,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return
    payment_id, payment_type = row
    if not ADMIN_ID:
        await update.message.reply_text('❗ Админ ID созланмаган. Администратор билан боғланинг.')
        return
    photo_id = update.message.photo[-1].file_id
    purpose = 'ЭЪЛОНЧИ' if payment_type == 'ads' else 'УСТА PRO'
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo_id,
            caption=(f'💳 ЯНГИ ТЎЛОВ ЧЕКИ — {purpose}\n\n'
                     f'🆔 Тўлов: #{payment_id}\n👤 Telegram ID: {tg}\n'
                     '💰 Сумма: 19 990 сўм / 30 кун\nТушумни текшириб, кейин тасдиқланг.'),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('✅ Тасдиқлаш', callback_data=f'payment_admin:approve:{payment_id}'),
                InlineKeyboardButton('❌ Рад этиш', callback_data=f'payment_admin:reject:{payment_id}')
            ]])
        )
        context.user_data.pop('pending_payment_id', None)
        context.user_data.pop('pending_payment_type', None)
        await update.message.reply_text('📨 Чек администраторга юборилди. Тўлов текширилгандан кейин обуна ёқилади.')
    except Exception:
        logger.exception('admin payment receipt delivery failed')
        await update.message.reply_text('❌ Чекни администраторга юборишда хатолик. Кейинроқ қайта урининг.')


async def admin_payment_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not admin_ok(update):
        await q.edit_message_text('❌ Рухсат йўқ.')
        return
    parts = q.data.split(':')
    if len(parts) != 3:
        await q.edit_message_text('❌ Нотўғри тўлов сўрови.')
        return
    action, payment_id = parts[1], int(parts[2])
    conn = get_connection()
    worker_tg = None
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,worker_id,telegram_id,amount,status,COALESCE(subscription_type,'worker')
                           FROM subscription_payments WHERE id=%s FOR UPDATE''', (payment_id,))
            p = cur.fetchone()
            if not p:
                await q.edit_message_text('❗ Тўлов сўрови топилмади.')
                return
            _, worker_id, worker_tg, amount, status, subscription_type = p
            if status != 'pending':
                await q.edit_message_text(f'⚠️ Бу тўлов аллақачон кўриб чиқилган: {status}')
                return
            now = datetime.now(timezone.utc)
            if action == 'approve':
                if subscription_type == 'ads':
                    cur.execute('SELECT subscription_until FROM user_subscriptions WHERE telegram_id=%s FOR UPDATE', (worker_tg,))
                    row = cur.fetchone()
                    old_until = row[0] if row else None
                    start = old_until if old_until and old_until > now else now
                    new_until = start + timedelta(days=SUBSCRIPTION_DAYS)
                    cur.execute('''INSERT INTO user_subscriptions(telegram_id,subscription_until,payment_pending,updated_at)
                                   VALUES(%s,%s,FALSE,NOW())
                                   ON CONFLICT(telegram_id) DO UPDATE SET subscription_until=EXCLUDED.subscription_until,
                                   payment_pending=FALSE,updated_at=NOW()''', (worker_tg, new_until))
                else:
                    cur.execute('SELECT subscription_until FROM workers WHERE id=%s FOR UPDATE', (worker_id,))
                    row = cur.fetchone()
                    old_until = row[0] if row else None
                    start = old_until if old_until and old_until > now else now
                    new_until = start + timedelta(days=SUBSCRIPTION_DAYS)
                    cur.execute('UPDATE workers SET subscription_until=%s,payment_pending=FALSE WHERE id=%s', (new_until, worker_id))
                cur.execute("UPDATE subscription_payments SET status='approved',reviewed_at=NOW(),reviewed_by=%s WHERE id=%s", (ADMIN_ID, payment_id))
                message = f'✅ Тўлов #{payment_id} тасдиқланди.\n\n♾️ Ойлик обуна {new_until.astimezone().strftime("%d.%m.%Y %H:%M")} гача фаол.'
            else:
                cur.execute("UPDATE subscription_payments SET status='rejected',reviewed_at=NOW(),reviewed_by=%s WHERE id=%s", (ADMIN_ID, payment_id))
                if subscription_type == 'ads':
                    cur.execute('UPDATE user_subscriptions SET payment_pending=FALSE,updated_at=NOW() WHERE telegram_id=%s', (worker_tg,))
                elif worker_id:
                    cur.execute('UPDATE workers SET payment_pending=FALSE WHERE id=%s', (worker_id,))
                message = f'❌ Тўлов #{payment_id} рад этилди. Агар тўлов қилган бўлсангиз, администратор билан боғланинг.'
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception('payment approval failed')
        await q.edit_message_text('❌ Тўловни қайта ишлашда хатолик юз берди.')
        return
    finally:
        conn.close()
    await q.edit_message_text(f'#{payment_id} — {"✅ ТАСДИҚЛАНДИ" if action == "approve" else "❌ РАД ЭТИЛДИ"}')
    try:
        await context.bot.send_message(chat_id=worker_tg, text=message)
    except Exception:
        logger.exception('subscription payment result notification failed')


async def start(update, context):
    loc = get_location(update.effective_user.id)
    if not loc:
        await update.message.reply_text('🛠 TEZ Service ботга хуш келибсиз!\n\n🌍 Аввало давлатни танланг:', reply_markup=country_keyboard())
        return LOCATION_COUNTRY
    await update.message.reply_text(
        f"🛠 TEZ Service ботга хуш келибсиз!\n\n🌍 Давлат: {loc['country_name']}\n🏙 Шаҳар: {loc['city']}\n\nКеракли хизматни танланг:",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END


async def location_menu_start(update, context):
    await update.message.reply_text('🌍 Давлатни танланг:', reply_markup=country_keyboard())
    return LOCATION_COUNTRY


async def location_country(update, context):
    t = update.message.text
    if t not in COUNTRIES:
        await update.message.reply_text('❗ Давлатни тугма орқали танланг.', reply_markup=country_keyboard())
        return LOCATION_COUNTRY
    d = COUNTRIES[t]
    context.user_data['loc'] = {'name': t, 'code': d['code'], 'currency': d['currency']}
    await update.message.reply_text(f'✅ {t}\n\n🏙 Энди шаҳарни танланг:', reply_markup=city_keyboard(t))
    return LOCATION_CITY


async def location_city(update, context):
    t = update.message.text
    if t == '⬅️ Бош меню':
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
        return ConversationHandler.END
    if t == '✏️ Бошқа шаҳар':
        await update.message.reply_text('🏙 Шаҳар номини ёзинг:')
        context.user_data['custom_city'] = True
        return LOCATION_CITY
    d = context.user_data.get('loc')
    if not d:
        return LOCATION_COUNTRY
    save_location(update.effective_user.id, d['code'], d['name'], t, d['currency'])
    context.user_data.pop('loc', None)
    context.user_data.pop('custom_city', None)
    await update.message.reply_text(
        f"✅ ЖОЙЛАШУВ САҚЛАНДИ!\n\n🌍 Давлат: {d['name']}\n🏙 Шаҳар: {t}\n💰 Валюта: {d['currency']}\n\n🛠 Энди керакли хизматни танланг:",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END


async def services(update, context):
    await update.message.reply_text('🔧 Хизмат турини танланг:', reply_markup=service_keyboard())


async def worker_start(update, context):
    loc = get_location(update.effective_user.id)
    context.user_data['worker'] = {}
    if not loc:
        await update.message.reply_text('🌍 Аввало давлатни танланг:', reply_markup=country_keyboard())
        return WORKER_COUNTRY
    context.user_data['worker'].update(loc)
    await update.message.reply_text(f"🌍 Давлат: {loc['country_name']}\n🏙 Шаҳар: {loc['city']}\n\n👤 Исмингизни ёзинг:")
    return WORKER_NAME


async def worker_country(update, context):
    t = update.message.text
    if t not in COUNTRIES:
        await update.message.reply_text('❗ Давлатни танланг.', reply_markup=country_keyboard())
        return WORKER_COUNTRY
    d = COUNTRIES[t]
    context.user_data['worker'] = {'country_name': t, 'country_code': d['code'], 'currency': d['currency']}
    await update.message.reply_text('🏙 Шаҳарни танланг:', reply_markup=city_keyboard(t))
    return WORKER_CITY


async def worker_city(update, context):
    t = update.message.text
    if t == '⬅️ Бош меню':
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
        return ConversationHandler.END
    if t == '✏️ Бошқа шаҳар':
        await update.message.reply_text('🏙 Шаҳар номини ёзинг:')
        return WORKER_CITY
    context.user_data['worker']['city'] = t
    await update.message.reply_text('👤 Исмингизни ёзинг:')
    return WORKER_NAME


async def worker_name(update, context):
    context.user_data['worker']['name'] = update.message.text.strip()
    await update.message.reply_text('📞 Телефон рақамингизни ёзинг:')
    return WORKER_PHONE


async def worker_phone(update, context):
    p = update.message.text.strip()
    if len(re.sub(r'\D', '', p)) < 7:
        await update.message.reply_text('❗ Телефон рақами нотўғри.')
        return WORKER_PHONE
    context.user_data['worker']['phone'] = p
    context.user_data['worker']['selected_services'] = []
    await update.message.reply_text(service_selection_prompt(), reply_markup=service_keyboard(multi=True))
    return WORKER_SERVICE


async def worker_service(update, context):
    text = (update.message.text or '').strip()
    w = context.user_data.setdefault('worker', {})
    selected = w.setdefault('selected_services', [])
    if text == '⬅️ Бош меню':
        context.user_data.pop('worker', None)
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
        return ConversationHandler.END
    if text == '✅ Танловни тасдиқлаш':
        if not selected:
            await update.message.reply_text('❗ Камида битта хизматни танланг.', reply_markup=service_keyboard(selected, multi=True))
            return WORKER_SERVICE
        w['service'] = ', '.join(selected)
        await update.message.reply_text('📍 Ҳудудингизни ёзинг:')
        return WORKER_AREA
    service = text.removeprefix('☑️ ').removeprefix('⬜ ')
    if service not in SERVICES:
        await update.message.reply_text('❗ Хизматларни тугма орқали танланг.', reply_markup=service_keyboard(selected, multi=True))
        return WORKER_SERVICE
    if service in selected:
        selected.remove(service)
    else:
        selected.append(service)
    await update.message.reply_text(service_selection_prompt(selected), reply_markup=service_keyboard(selected, multi=True))
    return WORKER_SERVICE


async def worker_area(update, context):
    context.user_data['worker']['area'] = update.message.text.strip()
    await update.message.reply_text('💰 Нарҳингизни ёзинг:')
    return WORKER_PRICE


async def worker_price(update, context):
    w = context.user_data['worker']
    tg = update.effective_user.id
    p = update.message.text.strip()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1', (tg,))
            r = cur.fetchone()
            if r:
                cur.execute('''UPDATE workers SET name=%s,phone=%s,service=%s,area=%s,price=%s,
                               country_code=%s,country_name=%s,city=%s,currency=%s,is_active=TRUE
                               WHERE id=%s''',
                            (w['name'], w['phone'], w['service'], w['area'], p, w['country_code'], w['country_name'], w['city'], w['currency'], r[0]))
            else:
                cur.execute('''INSERT INTO workers(telegram_id,name,phone,service,area,price,country_code,country_name,city,currency,is_active,free_orders_used)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,0)''',
                            (tg, w['name'], w['phone'], w['service'], w['area'], p, w['country_code'], w['country_name'], w['city'], w['currency']))
        conn.commit()
    finally:
        conn.close()
    sub = get_worker_subscription(tg)
    await update.message.reply_text(
        f"✅ Сиз уста сифатида муваффақиятли рўйхатдан ўтдингиз!\n\n"
        f"👤 {w['name']}\n📞 {w['phone']}\n🔧 {w['service']}\n🌍 {w['country_name']}\n"
        f"🏙 {w['city']}\n📍 {w['area']}\n💰 {p} {w['currency']}\n📌 Ҳолат: 🟢 Фаол\n\n"
        f"{subscription_text(sub)}",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END


async def profile(update, context):
    tg = update.effective_user.id
    repair_old_workers()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,name,phone,service,area,price,country_code,country_name,city,currency,created_at,COALESCE(is_active,TRUE),COALESCE(free_orders_used,0),subscription_until,COALESCE(payment_pending,FALSE)
                           FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1''', (tg,))
            w = cur.fetchone()
    finally:
        conn.close()
    if not w:
        await update.message.reply_text('❗ Сиз ҳали уста сифатида рўйхатдан ўтмагансиз.', reply_markup=worker_menu_keyboard())
        return
    wid,name,phone,service,area,price,cc,cn,city,curr,created,active,free_used,sub_until,pending = w
    sub = get_worker_subscription(tg)
    sub_line = subscription_text(sub)
    buttons = [
        [InlineKeyboardButton('✏️ Профилни таҳрирлаш', callback_data='worker_edit')],
        [InlineKeyboardButton('🔄 Фаол/нофаол', callback_data='toggle')]
    ]
    if not sub or not sub['subscribed']:
        buttons.append([InlineKeyboardButton('💳 PRO — 19 990 сўм/ой', callback_data='payment:info')])
    await update.message.reply_text(
        f"👤 МЕНИНГ ПРОФИЛИМ\n\n🌍 Давлат: {cn or '-'}\n🏙 Шаҳар: {city or '-'}\n"
        f"👤 Исм: {name}\n📞 Телефон: {phone}\n🔧 Хизмат: {service}\n📍 Ҳудуд: {area}\n"
        f"💰 Нархи: {price} {curr or ''}\n📌 Ҳолат: {'🟢 Фаол' if active else '🔴 Нофаол'}\n"
        f"🎁 Бепул қабул қилинган: {free_used}/{FREE_ORDER_LIMIT}\n\n{sub_line}\n\n🕐 Рўйхатдан ўтган: {created}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def toggle(update, context):
    q = update.callback_query
    await q.answer()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,COALESCE(is_active,TRUE) FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1', (q.from_user.id,))
            r = cur.fetchone()
            if not r:
                await q.edit_message_text('❗ Профиль топилмади.')
                return
            cur.execute('UPDATE workers SET is_active=%s WHERE id=%s', (not r[1], r[0]))
            new = not r[1]
        conn.commit()
    finally:
        conn.close()
    await q.edit_message_text(f"✅ Ҳолат ўзгартирилди: {'🟢 Фаол' if new else '🔴 Нофаол'}")


async def worker_edit_start(update, context):
    q = update.callback_query
    await q.answer()
    tg = q.from_user.id
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,name,phone,service,area,price,country_code,country_name,city,currency
                           FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1""", (tg,))
            w = cur.fetchone()
    finally:
        conn.close()
    if not w:
        await q.message.reply_text('❗ Уста профили топилмади.', reply_markup=worker_menu_keyboard())
        return ConversationHandler.END
    wid,name,phone,service,area,price,cc,cn,city,curr = w
    context.user_data['worker_edit'] = {
        'id': wid, 'name': name or '', 'phone': phone or '', 'service': service or '',
        'area': area or '', 'price': price or '', 'country_code': cc or '',
        'country_name': cn or country_name(cc) or '', 'city': city or '', 'currency': curr or currency(cc)
    }
    await q.message.reply_text('✏️ Профилни таҳрирлаш бошланди.\n\n🌍 Давлатни танланг:', reply_markup=country_keyboard())
    return EDIT_COUNTRY


async def worker_edit_country(update, context):
    t = update.message.text
    if t not in COUNTRIES:
        await update.message.reply_text('❗ Давлатни тугма орқали танланг.', reply_markup=country_keyboard())
        return EDIT_COUNTRY
    d = COUNTRIES[t]
    w = context.user_data['worker_edit']
    w.update({'country_name': t, 'country_code': d['code'], 'currency': d['currency'], 'city': ''})
    await update.message.reply_text('🏙 Шаҳарни танланг:', reply_markup=city_keyboard(t))
    return EDIT_CITY


async def worker_edit_city(update, context):
    t = update.message.text.strip()
    if t == '⬅️ Бош меню':
        context.user_data.pop('worker_edit', None)
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
        return ConversationHandler.END
    if t == '✏️ Бошқа шаҳар':
        await update.message.reply_text('🏙 Шаҳар номини ёзинг:')
        return EDIT_CITY
    if not t:
        await update.message.reply_text('❗ Шаҳарни киритинг.')
        return EDIT_CITY
    w = context.user_data['worker_edit']
    w['city'] = display_city(t)
    await update.message.reply_text(f"👤 Исмингизни ёзинг:\n\nҲозирги: {w['name'] or '-'}")
    return EDIT_NAME


async def worker_edit_name(update, context):
    value = update.message.text.strip()
    if not value:
        await update.message.reply_text('❗ Исмни киритинг.')
        return EDIT_NAME
    context.user_data['worker_edit']['name'] = value
    await update.message.reply_text(f"📞 Телефон рақамингизни ёзинг:\n\nҲозирги: {context.user_data['worker_edit']['phone'] or '-'}")
    return EDIT_PHONE


async def worker_edit_phone(update, context):
    p = update.message.text.strip()
    if len(re.sub(r'\D', '', p)) < 7:
        await update.message.reply_text('❗ Телефон рақами нотўғри.')
        return EDIT_PHONE
    w = context.user_data['worker_edit']
    w['selected_services'] = parse_selected_services(w.get('service', ''))
    await update.message.reply_text(service_selection_prompt(w['selected_services']), reply_markup=service_keyboard(w['selected_services'], multi=True))
    return EDIT_SERVICE


async def worker_edit_service(update, context):
    text = (update.message.text or '').strip()
    w = context.user_data['worker_edit']
    selected = w.setdefault('selected_services', [])
    if text == '⬅️ Бош меню':
        context.user_data.pop('worker_edit', None)
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
        return ConversationHandler.END
    if text == '✅ Танловни тасдиқлаш':
        if not selected:
            await update.message.reply_text('❗ Камида битта хизматни танланг.', reply_markup=service_keyboard(selected, multi=True))
            return EDIT_SERVICE
        w['service'] = ', '.join(selected)
        await update.message.reply_text(f"📍 Ҳудудингизни ёзинг:\n\nҲозирги: {w['area'] or '-'}")
        return EDIT_AREA
    service = text.removeprefix('☑️ ').removeprefix('⬜ ')
    if service not in SERVICES:
        await update.message.reply_text('❗ Хизматларни тугма орқали танланг.', reply_markup=service_keyboard(selected, multi=True))
        return EDIT_SERVICE
    if service in selected:
        selected.remove(service)
    else:
        selected.append(service)
    await update.message.reply_text(service_selection_prompt(selected), reply_markup=service_keyboard(selected, multi=True))
    return EDIT_SERVICE


async def worker_edit_area(update, context):
    value = update.message.text.strip()
    if not value:
        await update.message.reply_text('❗ Ҳудудни киритинг.')
        return EDIT_AREA
    context.user_data['worker_edit']['area'] = value
    await update.message.reply_text(f"💰 Нарҳингизни ёзинг:\n\nҲозирги: {context.user_data['worker_edit']['price'] or '-'}")
    return EDIT_PRICE


async def worker_edit_price(update, context):
    p = update.message.text.strip()
    if not p or not re.search(r'\d', p):
        await update.message.reply_text('❗ Нарҳни рақам билан киритинг.')
        return EDIT_PRICE
    w = context.user_data['worker_edit']
    tg = update.effective_user.id
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE workers SET name=%s,phone=%s,service=%s,area=%s,price=%s,
                           country_code=%s,country_name=%s,city=%s,currency=%s
                           WHERE id=%s AND telegram_id=%s""",
                        (w['name'], w['phone'], w['service'], w['area'], p,
                         w['country_code'], w['country_name'], w['city'], w['currency'], w['id'], tg))
            if cur.rowcount == 0:
                conn.rollback()
                context.user_data.pop('worker_edit', None)
                await update.message.reply_text('❗ Профиль топилмади.')
                return ConversationHandler.END
        conn.commit()
    finally:
        conn.close()
    context.user_data.pop('worker_edit', None)
    sub = get_worker_subscription(tg)
    await update.message.reply_text(
        f"✅ Профиль муваффақиятли янгиланди!\n\n🌍 Давлат: {w['country_name']}\n🏙 Шаҳар: {w['city']}\n"
        f"👤 Исм: {w['name']}\n📞 Телефон: {w['phone']}\n🔧 Хизмат: {w['service']}\n"
        f"📍 Ҳудуд: {w['area']}\n💰 Нархи: {p} {w['currency']}\n\n{subscription_text(sub)}",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END


async def order_service(update, context):
    s = update.message.text
    if s not in SERVICES:
        return ORDER_SERVICE
    loc = get_location(update.effective_user.id)
    if not loc:
        await update.message.reply_text('❗ Аввало давлат ва шаҳарни танланг.')
        return ConversationHandler.END
    context.user_data['order'] = {'service': s}
    await update.message.reply_text('👤 Исмингизни ёзинг:')
    return ORDER_NAME


async def order_name(update, context):
    context.user_data['order']['name'] = update.message.text.strip()
    await update.message.reply_text('📞 Телефон рақамингизни ёзинг:')
    return ORDER_PHONE


async def order_phone(update, context):
    p = update.message.text.strip()
    if len(re.sub(r'\D', '', p)) < 7:
        await update.message.reply_text('❗ Телефон рақами нотўғри.')
        return ORDER_PHONE
    context.user_data['order']['phone'] = p
    await update.message.reply_text('📍 Манзилингизни ёзинг:')
    return ORDER_ADDRESS


def detect_city_from_text(text):
    """Манзил матни ичида танилган шаҳарни топади."""
    s = normalize_text(text)
    if not s:
        return ''
    compact = s.replace(' ', '')
    # Узунроқ номларни аввал текшириш хавфини камайтиради.
    for city in sorted(CITY_COUNTRY, key=len, reverse=True):
        if city in compact:
            return city
    return ''


async def order_address(update, context):
    address = update.message.text.strip()
    context.user_data['order']['address'] = address

    detected_city = detect_city_from_text(address)
    if detected_city:
        code = country_from_city(detected_city)
        context.user_data['order']['city'] = display_city(detected_city)
        context.user_data['order']['country_code'] = code
        context.user_data['order']['country_name'] = country_name(code)
        context.user_data['order']['currency'] = currency(code)

    await update.message.reply_text('📝 Муаммони ёзинг:')
    return ORDER_PROBLEM


async def order_problem(update, context):
    tg = update.effective_user.id
    o = context.user_data['order']
    o['problem'] = update.message.text.strip()
    o['telegram_id'] = tg
    profile_loc = get_location(tg)
    if not profile_loc:
        await update.message.reply_text('❗ Аввало давлат ва шаҳарни танланг.')
        return ConversationHandler.END

    loc = dict(profile_loc)
    if o.get('city'):
        loc.update({
            'city': o['city'],
            'country_code': o.get('country_code') or profile_loc['country_code'],
            'country_name': o.get('country_name') or profile_loc['country_name'],
            'currency': o.get('currency') or currency(o.get('country_code')) or profile_loc['currency'],
        })

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO orders(telegram_id,name,phone,service,address,problem,status,country_code,country_name,city,currency)
                           VALUES(%s,%s,%s,%s,%s,%s,'new',%s,%s,%s,%s) RETURNING id''',
                        (tg, o['name'], o['phone'], o['service'], o['address'], o['problem'], loc['country_code'], loc['country_name'], loc['city'], loc['currency']))
            oid = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    await update.message.reply_text(
        f"✅ Буюртмангиз қабул қилинди!\n\n🆔 Буюртма: #{oid}\n🌍 {loc['country_name']}\n🏙 {loc['city']}\n🔧 {o['service']}\n\n⏳ Мос фаол усталар қидирилмоқда...",
        reply_markup=main_keyboard()
    )
    await send_order_to_workers(context, oid, o, loc)
    context.user_data.pop('order', None)
    return ConversationHandler.END


async def send_order_to_workers(context, oid, o, loc):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,telegram_id,name,phone,service,area,price,country_code,country_name,city,currency,COALESCE(is_active,TRUE)
                           FROM workers WHERE telegram_id IS NOT NULL AND COALESCE(is_active,TRUE)=TRUE AND COALESCE(is_blocked,FALSE)=FALSE ORDER BY id DESC''')
            rows = cur.fetchall()
    finally:
        conn.close()
    target_country = canonical_country(loc['country_code']) or canonical_country(loc['country_name']) or country_from_city(loc['city'])
    target_city = canonical_city(loc['city'])
    sent = set()
    found = 0
    for r in rows:
        wid,wtg,wname,wphone,wservice,warea,wprice,wcc,wcn,wcity,wcurr,active = r
        code,cname,cty,curr = infer_worker_location(wcc,wcn,wcity,warea)
        if code != target_country or canonical_city(cty) != target_city or not service_matches(wservice, o['service']):
            continue
        conn2 = get_connection()
        try:
            with conn2.cursor() as cur2:
                cur2.execute('UPDATE workers SET country_code=%s,country_name=%s,city=%s,currency=%s WHERE id=%s', (code,cname,cty,curr,wid))
            conn2.commit()
        finally:
            conn2.close()
        if wtg in sent:
            continue
        try:
            await context.bot.send_message(
                chat_id=wtg,
                text=(f"🔔 ЯНГИ БУЮРТМА!\n\n🆔 Буюртма: #{oid}\n🔧 Хизмат: {o['service']}\n"
                      f"👤 Мижоз: {o['name']}\n📞 Телефон: {o['phone']}\n📍 Манзил: {o['address']}\n"
                      f"📝 Муаммо: {o['problem']}\n\n🌍 {loc['country_name']}\n🏙 {loc['city']}"),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Буюртмани қабул қилиш', callback_data=f'accept:{oid}')]])
            )
            sent.add(wtg)
            found += 1
        except Exception:
            logger.exception('worker notification failed for %s', wtg)
    if found == 0:
        await context.bot.send_message(chat_id=o['telegram_id'], text=f'⚠️ Буюртма #{oid} учун ҳозирча мос фаол уста топилмади.')


async def accept_order(update, context):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.split(':')[1])
    tg = q.from_user.id
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,name,phone,country_code,country_name,city,COALESCE(is_active,TRUE),COALESCE(is_blocked,FALSE)
                           FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1''', (tg,))
            w = cur.fetchone()
            if not w:
                await q.edit_message_text('❗ Уста профили топилмади.')
                return
            wid,wname,wphone,wcc,wcn,wcity,wactive,wblocked = w
            if wblocked:
                await q.edit_message_text('⛔ Администратор профилингизни блоклаган. Администратор билан боғланинг.')
                return
            if not wactive:
                await q.edit_message_text('🔴 Профилингиз нофаол.')
                return

            # Lock both worker and order rows so two simultaneous clicks cannot bypass the 7-order limit.
            cur.execute('''SELECT COALESCE(free_orders_used,0),subscription_until
                           FROM workers WHERE id=%s FOR UPDATE''', (wid,))
            subrow = cur.fetchone()
            free_used = subrow[0]
            subscription_until = subrow[1]
            now = datetime.now(timezone.utc)
            subscribed = bool(subscription_until and subscription_until > now)
            if not subscribed and free_used >= FREE_ORDER_LIMIT:
                await q.edit_message_text(
                    '🔒 Сиз 7 та бепул буюртмани қабул қилиб бўлдингиз.\n\n'
                    '💳 Давом этиш учун ойига 19 990 сўмлик PRO обуна керак.',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('💳 19 990 сўм — PRO', callback_data='payment:info')]])
                )
                return

            cur.execute('''SELECT id,telegram_id,name,phone,service,address,problem,country_code,country_name,city,status
                           FROM orders WHERE id=%s FOR UPDATE''', (oid,))
            o = cur.fetchone()
            if not o:
                await q.edit_message_text('❗ Буюртма топилмади.')
                return
            _,ctg,cname,cphone,service,address,problem,occ,ocn,ocity,status = o
            if status != 'new':
                await q.edit_message_text('⚠️ Бу буюртма аллақачон қабул қилинган.')
                return

            wcode = canonical_country(wcc) or canonical_country(wcn) or country_from_city(wcity)
            ocode = canonical_country(occ) or canonical_country(ocn) or country_from_city(ocity)
            if wcode != ocode or not city_matches(wcity, ocity):
                await q.edit_message_text('❌ Бу буюртма сизнинг давлат/шаҳарингиз учун эмас.')
                return

            cur.execute('SELECT service FROM workers WHERE id=%s', (wid,))
            ws = cur.fetchone()[0]
            if not service_matches(ws, service):
                await q.edit_message_text('❌ Бу хизмат сизнинг профилингизга мос эмас.')
                return

            cur.execute("UPDATE orders SET status='accepted',accepted_worker_id=%s,accepted_worker_name=%s,accepted_at=NOW() WHERE id=%s AND status='new'", (wid,wname,oid))
            if cur.rowcount == 0:
                await q.edit_message_text('⚠️ Буюртмани бошқа уста қабул қилди.')
                conn.rollback()
                return

            if not subscribed:
                cur.execute('UPDATE workers SET free_orders_used=COALESCE(free_orders_used,0)+1 WHERE id=%s', (wid,))
                new_free_used = free_used + 1
            else:
                new_free_used = free_used

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception('accept_order failed')
        await q.edit_message_text('❌ Буюртмани қабул қилишда хатолик юз берди. Қайта уриниб кўринг.')
        return
    finally:
        conn.close()

    extra = ''
    if not subscribed:
        if new_free_used < FREE_ORDER_LIMIT:
            extra = f'\n\n🎁 Бепул қолган: {FREE_ORDER_LIMIT - new_free_used} та'
        else:
            extra = '\n\n🔒 Кейинги буюртмалар учун ойига 19 990 сўмлик PRO обуна керак.'
    await q.edit_message_text(
        f'✅ БУЮРТМА ҚАБУЛ ҚИЛИНДИ!\n\n👤 Мижоз: {cname}\n📞 Телефон: {cphone}\n'
        f'🔧 Хизмат: {service}\n📍 Манзил: {address}\n📝 Муаммо: {problem}{extra}'
    )
    try:
        await context.bot.send_message(chat_id=ctg, text=f'✅ Буюртмангиз қабул қилинди!\n\n👨‍🔧 Уста: {wname}\n📞 Телефон: {wphone}\n🔧 Хизмат: {service}\n📍 Шаҳар: {wcity}')
    except Exception:
        logger.exception('customer notification failed')


def get_announcement_subscription(telegram_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT subscription_until,COALESCE(payment_pending,FALSE) FROM user_subscriptions WHERE telegram_id=%s', (telegram_id,))
            row = cur.fetchone()
            cur.execute('SELECT COUNT(*) FROM announcements WHERE telegram_id=%s', (telegram_id,))
            count = cur.fetchone()[0]
            until = row[0] if row else None
            pending = row[1] if row else False
            now = datetime.now(timezone.utc)
            return {'count': count, 'subscription_until': until, 'subscribed': bool(until and until > now), 'payment_pending': pending}
    finally:
        conn.close()


async def announcement_start(update, context):
    tg = update.effective_user.id
    sub = get_announcement_subscription(tg)
    if not sub['subscribed'] and sub['count'] >= FREE_ANNOUNCEMENT_LIMIT:
        await update.message.reply_text(
            '🔒 Сиз 7 та бепул эълон жойлаштирдингиз.\n\n'
            '📢 Кейинги эълонларни жойлаштириш учун ойлик обуна керак.\n'
            '💰 Нархи: 19 990 сўм / 30 кун.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('💳 Эълонлар учун обуна', callback_data='payment:ads_info')],
                                               [InlineKeyboardButton('✅ Тўладим', callback_data='payment:ads_paid')]])
        )
        return ConversationHandler.END
    context.user_data['ann'] = {}
    await update.message.reply_text(
        f'📢 Эълон бериш: {sub["count"]}/{FREE_ANNOUNCEMENT_LIMIT} та бепул эълон ишлатилган.\n\n'
        '🌍 Эълонингиз учун давлатни танланг:', reply_markup=country_keyboard())
    return ANN_COUNTRY


async def ann_country(update, context):
    t = update.message.text
    if t not in COUNTRIES:
        await update.message.reply_text('❗ Давлатни танланг.', reply_markup=country_keyboard())
        return ANN_COUNTRY
    d = COUNTRIES[t]
    context.user_data['ann'] = {'country_name':t,'country_code':d['code'],'currency':d['currency']}
    await update.message.reply_text('🏙 Шаҳарни танланг:', reply_markup=city_keyboard(t))
    return ANN_CITY


async def ann_city(update, context):
    t = update.message.text
    if t == '✏️ Бошқа шаҳар':
        await update.message.reply_text('🏙 Шаҳар номини ёзинг:')
        return ANN_CITY
    context.user_data['ann']['city'] = t.strip()
    await update.message.reply_text('👤 Исмингизни ёзинг:')
    return ANN_NAME


async def ann_name(update, context):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text('❗ Исмингизни тўғри киритинг.')
        return ANN_NAME
    context.user_data['ann']['name'] = name
    await update.message.reply_text('📞 Телефон рақамингизни ёзинг:')
    return ANN_PHONE


async def ann_phone(update, context):
    p = update.message.text.strip()
    if len(re.sub(r'\D', '', p)) < 7:
        await update.message.reply_text('❗ Телефон рақами нотўғри.')
        return ANN_PHONE
    context.user_data['ann']['phone'] = p
    await update.message.reply_text('📢 Эълон турини танланг:', reply_markup=announcement_type_keyboard())
    return ANN_SERVICE


async def ann_service(update, context):
    if update.message.text not in ANNOUNCEMENT_TYPES:
        await update.message.reply_text('❗ Эълон турини тугма орқали танланг.', reply_markup=announcement_type_keyboard())
        return ANN_SERVICE
    context.user_data['ann']['service'] = update.message.text
    await update.message.reply_text('📝 Эълон сарлавҳасини ёзинг. Масалан: «Телефонимни сотаман» ёки «1 хонали уй ижарага берилади»:')
    return ANN_ADDRESS


async def ann_address(update, context):
    title = update.message.text.strip()
    if len(title) < 3:
        await update.message.reply_text('❗ Эълон сарлавҳасини тўлиқроқ ёзинг:')
        return ANN_ADDRESS
    context.user_data['ann']['address'] = title
    await update.message.reply_text('💰 Нархини ёзинг ёки «Келишилади» деб ёзинг:')
    return ANN_BUDGET


async def ann_budget(update, context):
    context.user_data['ann']['budget'] = update.message.text.strip()[:200]
    await update.message.reply_text('📝 Эълон ҳақида қўшимча маълумот ёзинг (масалан, ҳолати, ҳужжатлари ёки шартлари).')
    return ANN_DETAILS


async def ann_details(update, context):
    a = context.user_data['ann']
    a['details'] = update.message.text.strip()
    tg = update.effective_user.id
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO announcements(telegram_id,name,phone,service,address,budget,details,country_code,country_name,city,currency) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (tg,a['name'],a['phone'],a['service'],a['address'],a['budget'],a['details'],a['country_code'],a['country_name'],a['city'],a['currency']))
            aid = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    ad_text = (f'📢 ЯНГИ ЭЪЛОН — TEZ Service\n\n🆔 #{aid}\n📌 Тур: {a["service"]}\n'
               f'📝 {a["address"]}\n💰 Нарх: {a["budget"]}\n🌍 {a["country_name"]}\n'
               f'🏙 Шаҳар: {a["city"]}\n👤 {a["name"]}\n📞 Алоқа: {a["phone"]}\n'
               f'ℹ️ {a["details"]}')
    await update.message.reply_text(
        f'✅ Эълонингиз қабул қилинди ва бот фойдаланувчиларига юборилмоқда!\n\n'
        f'🆔 Эълон: #{aid}\n📢 Тур: {a["service"]}\n📝 {a["address"]}',
        reply_markup=main_keyboard()
    )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT telegram_id FROM bot_users WHERE telegram_id IS NOT NULL UNION SELECT telegram_id FROM user_profiles WHERE telegram_id IS NOT NULL UNION SELECT telegram_id FROM workers WHERE telegram_id IS NOT NULL UNION SELECT telegram_id FROM orders WHERE telegram_id IS NOT NULL UNION SELECT telegram_id FROM announcements WHERE telegram_id IS NOT NULL")
            recipients = [row[0] for row in cur.fetchall() if row[0]]
    finally:
        conn.close()

    sent = 0
    failed = 0
    for recipient in recipients:
        try:
            await context.bot.send_message(chat_id=recipient, text=ad_text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as exc:
            failed += 1
            logger.info('Announcement #%s could not be delivered to %s: %s', aid, recipient, exc)

    if ADMIN_ID and ADMIN_ID not in recipients:
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=ad_text)
        except Exception:
            logger.exception('admin announcement notification failed')
    logger.info('Announcement #%s broadcast complete: sent=%s failed=%s', aid, sent, failed)
    context.user_data.pop('ann', None)
    return ConversationHandler.END


async def help_cmd(update, context):
    await update.message.reply_text(
        '📖 Буйруқлар:\n/start — Бошлаш\n/help — Ёрдам\n/workers — Усталар (админ)\n'
        '/orders — Буюртмалар (админ)\n/announcements — Эълонлар (админ)\n/stats — Статистика (админ)\n'
        '/payments — PRO тўловлар (админ)'
    )


def admin_ok(update):
    return ADMIN_ID and update.effective_user.id == ADMIN_ID


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('👨‍🔧 Усталар', callback_data='admin:workers'),
            InlineKeyboardButton('🔔 Буюртмалар', callback_data='admin:orders')
        ],
        [
            InlineKeyboardButton('📢 Эълонлар', callback_data='admin:announcements'),
            InlineKeyboardButton('💳 Тўловлар', callback_data='admin:payments')
        ],
        [InlineKeyboardButton('📊 Статистика', callback_data='admin:stats')],
        [InlineKeyboardButton('📢 Хабар юбориш', callback_data='admin:broadcast')],
        [InlineKeyboardButton('💳 Тўлов реквизитлари', callback_data='admin:payment_settings')]
    ])


async def admin_cmd(update, context):
    if not ADMIN_ID:
        await update.effective_message.reply_text(
            '❌ ADMIN_ID Render Environment Variables да ўрнатилмаган.'
        )
        return
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return
    await update.effective_message.reply_text(
        '🛠 ADMIN PANEL\n\nКеракли бўлимни танланг:',
        reply_markup=admin_keyboard()
    )


async def admin_menu_callback(update, context):
    q = update.callback_query
    if not admin_ok(update):
        await q.answer('❌ Рухсат йўқ.', show_alert=True)
        return
    await q.answer()
    action = q.data.split(':', 1)[1]
    if action == 'workers':
        await workers_cmd(update, context)
    elif action == 'orders':
        await orders_cmd(update, context)
    elif action == 'announcements':
        await announcements_cmd(update, context)
    elif action == 'payments':
        await payments_cmd(update, context)
    elif action == 'stats':
        await stats_cmd(update, context)
    elif action == 'payment_settings':
        await admin_payment_settings(update, context)
    elif action == 'broadcast':
        await q.message.reply_text(
            '📢 ХАБАР ЮБОРИШ\n\nКимга хабар юборамиз?',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('👥 Барча фойдаланувчиларга', callback_data='broadcast:all')],
                [InlineKeyboardButton('👨‍🔧 Фақат усталарга', callback_data='broadcast:workers')],
                [InlineKeyboardButton('👤 Telegram ID орқали битта одамга', callback_data='broadcast:user')],
                [InlineKeyboardButton('⬅️ Админ панел', callback_data='admin:back')]
            ])
        )
    elif action == 'back':
        await q.message.reply_text('🛠 ADMIN PANEL\n\nКеракли бўлимни танланг:', reply_markup=admin_keyboard())


async def admin_payment_settings(update, context):
    q = update.callback_query
    if not admin_ok(update):
        await q.answer('❌ Рухсат йўқ.', show_alert=True)
        return
    details = get_payment_details()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('✏️ Реквизитларни ўзгартириш', callback_data='admin:payment_edit')],
        [InlineKeyboardButton('⬅️ Админ панел', callback_data='admin:back')]
    ])
    await q.message.reply_text(
        '💳 ТЎЛОВ РЕКВИЗИТЛАРИ\n\n'
        f'Ҳозирги маълумот:\n{details}\n\n'
        'Ўзгартириш тугмасини босиб, карта рақами, карта эгаси ва банк маълумотларини битта хабарда юборинг.',
        reply_markup=keyboard
    )


ADMIN_PAYMENT_DETAILS = 60
ADMIN_BROADCAST_TEXT = 70
ADMIN_BROADCAST_USER_ID = 71


async def admin_payment_edit_start(update, context):
    q = update.callback_query
    if not admin_ok(update):
        await q.answer('❌ Рухсат йўқ.', show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await q.message.reply_text(
        '✏️ Янги тўлов реквизитларини битта хабарда юборинг.\n\n'
        'Масалан:\nБанк: MBANK\nКарта: 0000 0000 0000 0000\nКарта эгаси: ИСМ ФАМИЛИЯ\nВалюта: сом\n\n'
        'Бекор қилиш учун /cancel юборинг.'
    )
    return ADMIN_PAYMENT_DETAILS


async def admin_payment_details_save(update, context):
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return ConversationHandler.END
    value = (update.effective_message.text or '').strip()
    if len(value) < 5 or len(value) > 2000:
        await update.effective_message.reply_text('❌ Маълумот 5 тадан 2000 тагача белги бўлиши керак. Қайта юборинг ёки /cancel босинг.')
        return ADMIN_PAYMENT_DETAILS
    save_payment_details(value)
    await update.effective_message.reply_text(
        '✅ Тўлов реквизитлари сақланди. Энди PRO тўлов маълумотини сўраган фойдаланувчиларга янги реквизитлар автоматик кўрсатилади.',
        reply_markup=admin_keyboard()
    )
    return ConversationHandler.END


async def admin_payment_edit_cancel(update, context):
    await update.effective_message.reply_text('❎ Реквизитларни ўзгартириш бекор қилинди.', reply_markup=admin_keyboard())
    return ConversationHandler.END


async def workers_cmd(update, context):
    """Админ учун усталар рўйхати ва бошқарув тугмалари."""
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (telegram_id) id,telegram_id,name,phone,service,country_name,city,price,
                                  COALESCE(is_active,TRUE),COALESCE(is_blocked,FALSE),COALESCE(free_orders_used,0),subscription_until
                           FROM workers WHERE telegram_id IS NOT NULL ORDER BY telegram_id,id DESC""")
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        await update.effective_message.reply_text('👨‍🔧 Усталар йўқ.')
        return
    await update.effective_message.reply_text(f'👨‍🔧 УСТАЛАР РЎЙХАТИ — жами: {len(rows)}')
    for r in rows[:100]:
        wid,tg,name,phone,service,cn,city,price,active,blocked,free_used,sub_until = r
        sub = '♾️ PRO' if sub_until and sub_until > datetime.now(timezone.utc) else f'🎁 {free_used}/{FREE_ORDER_LIMIT}'
        state = '⛔ БЛОКЛАНГАН' if blocked else ('🟢 Фаол' if active else '🔴 Нофаол')
        text = (f'🆔 Уста ID: {wid}\nTelegram ID: {tg}\n👤 {name or "-"}\n📞 {phone or "-"}\n'
                f'🔧 {service or "-"}\n🌍 {cn or "-"} — {city or "-"}\n💰 {price or "-"}\n{state}\n{sub}')
        buttons = []
        if blocked:
            buttons.append(InlineKeyboardButton('🟢 Блокдан чиқариш', callback_data=f'workeradmin:unblock:{wid}'))
        else:
            buttons.append(InlineKeyboardButton('🔴 Блоклаш', callback_data=f'workeradmin:block:{wid}'))
        keyboard = InlineKeyboardMarkup([
            buttons,
            [InlineKeyboardButton('🗑 Аккаунтни ўчириш', callback_data=f'workeradmin:delete:{wid}')]
        ])
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def admin_worker_action(update, context):
    q = update.callback_query
    if not admin_ok(update):
        await q.answer('❌ Рухсат йўқ.', show_alert=True)
        return
    await q.answer()
    parts = q.data.split(':')
    if len(parts) != 3 or not parts[2].isdigit():
        await q.message.reply_text('❌ Нотўғри сўров.')
        return
    action, wid = parts[1], int(parts[2])
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT telegram_id,name FROM workers WHERE id=%s', (wid,))
            row = cur.fetchone()
            if not row:
                await q.message.reply_text('❗ Уста топилмади ёки аллақачон ўчирилган.')
                return
            worker_tg, worker_name = row
            if action == 'delete':
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton('🗑 Ҳа, ўчириш', callback_data=f'workeradmin:deleteconfirm:{wid}'),
                    InlineKeyboardButton('❌ Бекор қилиш', callback_data=f'workeradmin:deletecancel:{wid}')
                ]])
                await q.message.reply_text(
                    f'⚠️ {worker_name or worker_tg} устасининг профилини ўчирамизми?\n\n'
                    'Профил ёзувлари ўчирилади, буюртмалар ва тўловлар тарихи сақланади.',
                    reply_markup=keyboard
                )
                return
            if action == 'deletecancel':
                await q.message.reply_text('❎ Ўчириш бекор қилинди.')
                return
            if action == 'block':
                cur.execute('UPDATE workers SET is_blocked=TRUE,is_active=FALSE WHERE telegram_id=%s', (worker_tg,))
                result = f'🔴 {worker_name or worker_tg} блокланди. Профили ва тарихи сақланди.'
            elif action == 'unblock':
                cur.execute('UPDATE workers SET is_blocked=FALSE,is_active=TRUE WHERE telegram_id=%s', (worker_tg,))
                result = f'🟢 {worker_name or worker_tg} блокдан чиқарилди ва фаоллаштирилди.'
            elif action == 'deleteconfirm':
                cur.execute('DELETE FROM workers WHERE telegram_id=%s', (worker_tg,))
                result = f'🗑 {worker_name or worker_tg} устанинг профили ўчирилди. Тарих сақланди.'
            else:
                await q.message.reply_text('❌ Номаълум амал.')
                return
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception('admin worker action failed')
        await q.message.reply_text('❌ Амални бажаришда хатолик юз берди.')
        return
    finally:
        conn.close()
    await q.message.reply_text(result)


async def admin_broadcast_start(update, context):
    q = update.callback_query
    if not admin_ok(update):
        await q.answer('❌ Рухсат йўқ.', show_alert=True)
        return ConversationHandler.END
    await q.answer()
    target = q.data.split(':', 1)[1]
    context.user_data['admin_broadcast_target'] = target
    if target == 'user':
        await q.message.reply_text('👤 Фойдаланувчининг Telegram ID рақамини юборинг. Бекор қилиш: /cancel')
        return ADMIN_BROADCAST_USER_ID
    await q.message.reply_text('✍️ Юбориладиган хабар матнини ёзинг. Бекор қилиш: /cancel')
    return ADMIN_BROADCAST_TEXT


async def admin_broadcast_user_id(update, context):
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return ConversationHandler.END
    value = (update.effective_message.text or '').strip()
    if not value.isdigit():
        await update.effective_message.reply_text('❗ Telegram ID рақамлардан иборат бўлиши керак. Қайта юборинг ёки /cancel босинг.')
        return ADMIN_BROADCAST_USER_ID
    context.user_data['admin_broadcast_user_id'] = int(value)
    await update.effective_message.reply_text('✍️ Энди хабар матнини юборинг. Бекор қилиш: /cancel')
    return ADMIN_BROADCAST_TEXT


async def admin_broadcast_send(update, context):
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return ConversationHandler.END
    message = (update.effective_message.text or '').strip()
    if not message:
        await update.effective_message.reply_text('❗ Хабар бўш бўлмасин. Қайта юборинг ёки /cancel босинг.')
        return ADMIN_BROADCAST_TEXT
    target = context.user_data.get('admin_broadcast_target')
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if target == 'workers':
                cur.execute('SELECT DISTINCT telegram_id FROM workers WHERE telegram_id IS NOT NULL AND COALESCE(is_blocked,FALSE)=FALSE')
            elif target == 'user':
                cur.execute('SELECT telegram_id FROM user_profiles WHERE telegram_id=%s UNION SELECT telegram_id FROM workers WHERE telegram_id=%s',
                            (context.user_data.get('admin_broadcast_user_id'), context.user_data.get('admin_broadcast_user_id')))
            else:
                cur.execute("""SELECT telegram_id FROM bot_users WHERE telegram_id IS NOT NULL
                               UNION SELECT telegram_id FROM user_profiles WHERE telegram_id IS NOT NULL
                               UNION SELECT telegram_id FROM workers WHERE telegram_id IS NOT NULL
                               UNION SELECT telegram_id FROM orders WHERE telegram_id IS NOT NULL
                               UNION SELECT telegram_id FROM announcements WHERE telegram_id IS NOT NULL""")
            recipients = [r[0] for r in cur.fetchall() if r[0] and r[0] != ADMIN_ID]
    finally:
        conn.close()
    if target == 'user' and not recipients:
        recipients = [context.user_data.get('admin_broadcast_user_id')]
    if not recipients:
        await update.effective_message.reply_text('❗ Фойдаланувчилар топилмади.')
        return ConversationHandler.END
    context.user_data['admin_broadcast_message'] = message
    context.user_data['admin_broadcast_recipients'] = recipients
    labels = {'all':'барча фойдаланувчиларга', 'workers':'усталарга', 'user':'битта фойдаланувчига'}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton('✅ Юбориш', callback_data='broadcastconfirm:yes'),
        InlineKeyboardButton('❌ Бекор қилиш', callback_data='broadcastconfirm:no')
    ]])
    await update.effective_message.reply_text(
        f'📢 ХАБАРНИ ТЕКШИРИНГ\n\nҚабул қилувчилар: {labels.get(target, target)}\n'
        f'Сони: {len(recipients)}\n\nХабар:\n{message}\n\nЮборишни тасдиқлайсизми?',
        reply_markup=keyboard
    )
    return ConversationHandler.END


async def admin_broadcast_confirm(update, context):
    q = update.callback_query
    if not admin_ok(update):
        await q.answer('❌ Рухсат йўқ.', show_alert=True)
        return
    await q.answer()
    if q.data.endswith(':no'):
        await q.edit_message_text('❎ Хабар юбориш бекор қилинди.')
        for key in ('admin_broadcast_message','admin_broadcast_recipients','admin_broadcast_target','admin_broadcast_user_id'):
            context.user_data.pop(key, None)
        return
    message = context.user_data.get('admin_broadcast_message')
    recipients = context.user_data.get('admin_broadcast_recipients', [])
    if not message or not recipients:
        await q.edit_message_text('❗ Хабар маълумоти топилмади. Қайта бошланг: /admin')
        return
    sent = failed = 0
    for chat_id in recipients:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.info('broadcast failed for %s: %s', chat_id, exc)
    await q.edit_message_text(f'📊 ХАБАР ЮБОРИШ ЯКУНИ\n\n✅ Юборилди: {sent}\n❌ Юборилмади: {failed}\n👥 Жами: {len(recipients)}')
    for key in ('admin_broadcast_message','admin_broadcast_recipients','admin_broadcast_target','admin_broadcast_user_id'):
        context.user_data.pop(key, None)


async def admin_broadcast_cancel(update, context):
    for key in ('admin_broadcast_message','admin_broadcast_recipients','admin_broadcast_target','admin_broadcast_user_id'):
        context.user_data.pop(key, None)
    await update.effective_message.reply_text('❎ Хабар юбориш бекор қилинди.', reply_markup=admin_keyboard())
    return ConversationHandler.END

async def orders_cmd(update, context):
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,name,phone,service,country_name,city,status,created_at FROM orders ORDER BY id DESC LIMIT 100')
            rows = cur.fetchall()
    finally:
        conn.close()
    await update.effective_message.reply_text('\n'.join([
        f'#{r[0]} — {r[6]}\n👤 {r[1]}\n📞 {r[2]}\n🔧 {r[3]}\n🌍 {r[4] or "-"}\n🏙 {r[5] or "-"}\n🕐 {r[7]}\n' for r in rows
    ]) or '🔔 Буюртмалар йўқ.')


async def announcements_cmd(update, context):
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,name,phone,service,country_name,city,budget,details,created_at FROM announcements ORDER BY id DESC LIMIT 100')
            rows = cur.fetchall()
    finally:
        conn.close()
    await update.effective_message.reply_text('\n'.join([
        f'#{r[0]}\n👤 {r[1]}\n📞 {r[2]}\n🔧 {r[3]}\n🌍 {r[4] or "-"}\n🏙 {r[5] or "-"}\n💰 {r[6]}\n📝 {r[7]}\n🕐 {r[8]}\n' for r in rows
    ]) or '📢 Эълонлар йўқ.')


async def payments_cmd(update, context):
    """Админга тўловлар рўйхатини ва pending тўловлар учун амалий тугмаларни кўрсатади."""
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT p.id,p.worker_id,p.telegram_id,p.amount,p.currency,p.status,p.created_at,w.name,COALESCE(p.subscription_type,'worker')
                           FROM subscription_payments p LEFT JOIN workers w ON w.id=p.worker_id
                           ORDER BY p.id DESC LIMIT 50""")
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        await update.effective_message.reply_text('💳 Тўловлар йўқ.')
        return

    await update.effective_message.reply_text('💳 PRO ТЎЛОВЛАР:')
    for r in rows:
        payment_id, worker_id, telegram_id, amount, curr, status, created_at, worker_name, subscription_type = r
        text = (
            f'#{payment_id} — {status}\n'
            f'📌 Тур: {"Эълончи" if subscription_type == "ads" else "Уста PRO"}\n'
            f'👤 {worker_name or "Фойдаланувчи"}\n'
            f'🆔 {telegram_id}\n'
            f'💰 {amount} {curr}\n'
            f'🕐 {created_at}'
        )
        keyboard = None
        if status == 'pending':
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton('✅ Тасдиқлаш', callback_data=f'payment_admin:approve:{payment_id}'),
                InlineKeyboardButton('❌ Рад этиш', callback_data=f'payment_admin:reject:{payment_id}')
            ]])
            text += '\n\n⚠️ MBANK ҳисобида пул ҳақиқатан тушганини текширинг. Фақат шундан кейин тасдиқланг.'
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def stats_cmd(update, context):
    if not admin_ok(update):
        await update.effective_message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM workers'); w = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM workers WHERE COALESCE(is_active,TRUE)'); aw = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM orders'); o = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM announcements'); a = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM subscription_payments WHERE status='pending'"); pp = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM workers WHERE subscription_until > NOW()"); pro = cur.fetchone()[0]
    finally:
        conn.close()
    await update.effective_message.reply_text(
        f'📊 СТАТИСТИКА\n\n👨‍🔧 Жами усталар: {w}\n🟢 Фаол усталар: {aw}\n'
        f'♾️ PRO усталар: {pro}\n🔔 Буюртмалар: {o}\n📢 Эълонлар: {a}\n💳 Кутилаётган тўловлар: {pp}'
    )


async def contact(update, context):
    await update.message.reply_text('📞 Алоқа\n\nTEZ Service\nТаклиф ёки шикоятингизни «💡 Таклиф юбориш» ёки «⚠️ Шикоят юбориш» тугмалари орқали администраторга юборишингиз мумкин.')


async def feedback_start(update, context):
    text = update.effective_message.text or ''
    feedback_type = 'Таклиф' if text == '💡 Таклиф юбориш' else 'Шикоят'
    context.user_data['feedback_type'] = feedback_type
    await update.effective_message.reply_text(
        f'✍️ {feedback_type} матнини ёзиб юборинг.\n\nБекор қилиш учун /cancel буйруғини юборинг.'
    )
    return FEEDBACK_TEXT


async def feedback_receive(update, context):
    message = update.effective_message
    body = (message.text or '').strip()
    if not body:
        await message.reply_text('❗ Илтимос, матн кўринишида юборинг.')
        return FEEDBACK_TEXT
    user = update.effective_user
    feedback_type = context.user_data.get('feedback_type', 'Мурожаат')
    username = f'@{user.username}' if user.username else 'йўқ'
    admin_text = (
        f'📩 TEZ Service — янги {feedback_type.lower()}\n\n'
        f'👤 Исми: {user.full_name}\n'
        f'🔗 Username: {username}\n'
        f'🆔 Telegram ID: {user.id}\n\n'
        f'📝 Матн:\n{body}'
    )
    if not ADMIN_ID:
        await message.reply_text('❌ Администратор ID созланмаган. Кейинроқ қайта уриниб кўринг.')
        context.user_data.pop('feedback_type', None)
        return ConversationHandler.END
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
    except Exception:
        logger.exception('Failed to send feedback to admin')
        await message.reply_text('❌ Хабарни юбориб бўлмади. Илтимос, кейинроқ қайта урининг.')
        context.user_data.pop('feedback_type', None)
        return ConversationHandler.END
    await message.reply_text('✅ Мурожаатингиз администраторга юборилди. Раҳмат!', reply_markup=main_keyboard())
    context.user_data.pop('feedback_type', None)
    return ConversationHandler.END


async def feedback_cancel(update, context):
    context.user_data.pop('feedback_type', None)
    await update.effective_message.reply_text('❎ Мурожаат юбориш бекор қилинди.', reply_markup=main_keyboard())
    return ConversationHandler.END


async def cancel_to_menu(update, context):
    """Cancel any active conversation when the user presses the back-to-menu button."""
    for key in ('worker', 'worker_edit', 'order', 'announcement', 'loc', 'custom_city', 'feedback_type'):
        context.user_data.pop(key, None)
    await update.effective_message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
    return ConversationHandler.END


async def worker_menu(update, context):
    await update.message.reply_text('👨‍🔧 Уста бўлими:', reply_markup=worker_menu_keyboard())


async def generic_menu(update, context):
    t = update.message.text
    if t == '⬅️ Бош меню':
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())


async def track_user(update, context):
    """Remember every Telegram user who interacts with the bot for future broadcasts."""
    user = update.effective_user
    if not user or user.is_bot:
        return
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO bot_users(telegram_id,username,first_name,last_name,first_seen,last_seen) VALUES(%s,%s,%s,%s,NOW(),NOW()) ON CONFLICT(telegram_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name, last_seen=NOW()", (user.id,user.username,user.first_name,user.last_name))
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        logger.exception('Could not track bot user')
    finally:
        if conn:
            conn.close()


def build_application():
    app = Application.builder().token(BOT_TOKEN).build()
    # Track all message and button interactions before regular handlers run.
    app.add_handler(MessageHandler(filters.ALL, track_user), group=-1)
    app.add_handler(CallbackQueryHandler(track_user), group=-1)

    loc = ConversationHandler(
        entry_points=[CommandHandler('start', start), MessageHandler(filters.Regex(r'^🌍 Давлат/шаҳар$'), location_menu_start)],
        states={
            LOCATION_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), location_country)],
            LOCATION_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), location_city)]
        },
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('start', start)], allow_reentry=True
    )
    worker_edit = ConversationHandler(
        entry_points=[CallbackQueryHandler(worker_edit_start, pattern=r'^worker_edit$')],
        states={
            EDIT_COUNTRY: [MessageHandler(EDIT_INPUT_FILTER, worker_edit_country)],
            EDIT_CITY: [MessageHandler(EDIT_INPUT_FILTER, worker_edit_city)],
            EDIT_NAME: [MessageHandler(EDIT_INPUT_FILTER, worker_edit_name)],
            EDIT_PHONE: [MessageHandler(EDIT_INPUT_FILTER, worker_edit_phone)],
            EDIT_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), worker_edit_service)],
            EDIT_AREA: [MessageHandler(EDIT_INPUT_FILTER, worker_edit_area)],
            EDIT_PRICE: [MessageHandler(EDIT_INPUT_FILTER, worker_edit_price)]
        },
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('start', start)], allow_reentry=True
    )

    worker = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^👨‍🔧 Уста бўлиб рўйхатдан ўтиш$'), worker_start)],
        states={
            WORKER_COUNTRY:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_country)],
            WORKER_CITY:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_city)],
            WORKER_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_name)],
            WORKER_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_phone)],
            WORKER_SERVICE:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_service)],
            WORKER_AREA:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_area)],
            WORKER_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),worker_price)]
        },
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('start',start)]
    )
    order = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(SERVICE_PATTERN), order_service)],
        states={
            ORDER_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),order_name)],
            ORDER_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),order_phone)],
            ORDER_ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),order_address)],
            ORDER_PROBLEM:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),order_problem)]
        },
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('start',start)]
    )
    ann = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^📢 Эълон бериш$'), announcement_start)],
        states={
            ANN_COUNTRY:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_country)],
            ANN_CITY:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_city)],
            ANN_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_name)],
            ANN_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_phone)],
            ANN_SERVICE:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_service)],
            ANN_ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_address)],
            ANN_BUDGET:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_budget)],
            ANN_DETAILS:[MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN),ann_details)]
        },
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('start',start)]
    )

    feedback = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^(?:💡 Таклиф юбориш|⚠️ Шикоят юбориш)$'), feedback_start)],
        states={FEEDBACK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), feedback_receive)]},
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('cancel', feedback_cancel), CommandHandler('start', start)],
        allow_reentry=True
    )

    app.add_handler(feedback)
    app.add_handler(worker_edit)
    app.add_handler(loc)
    app.add_handler(worker)
    app.add_handler(ann)
    app.add_handler(order)
    admin_payment_edit = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_payment_edit_start, pattern=r'^admin:payment_edit$')],
        states={ADMIN_PAYMENT_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), admin_payment_details_save)]},
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('cancel', admin_payment_edit_cancel), CommandHandler('start', start)],
        allow_reentry=True
    )
    app.add_handler(admin_payment_edit)
    admin_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern=r'^broadcast:(all|workers|user)$')],
        states={
            ADMIN_BROADCAST_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), admin_broadcast_user_id)],
            ADMIN_BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(BACK_MENU_PATTERN), admin_broadcast_send)]
        },
        fallbacks=[MessageHandler(BACK_MENU_FILTER, cancel_to_menu), CommandHandler('cancel', admin_broadcast_cancel), CommandHandler('start', start)],
        allow_reentry=True
    )
    app.add_handler(admin_broadcast)
    app.add_handler(CallbackQueryHandler(admin_broadcast_confirm, pattern=r'^broadcastconfirm:(yes|no)$'))
    app.add_handler(CallbackQueryHandler(admin_worker_action, pattern=r'^workeradmin:(block|unblock|delete|deleteconfirm|deletecancel):\d+$'))
    app.add_handler(CallbackQueryHandler(admin_payment_callback, pattern=r'^payment_admin:(approve|reject):\d+$'))
    app.add_handler(CallbackQueryHandler(payment_callback, pattern=r'^payment:(info|paid|worker_info|worker_paid|ads_info|ads_paid)$'))
    app.add_handler(MessageHandler(filters.PHOTO, payment_receipt_photo))
    app.add_handler(CallbackQueryHandler(accept_order, pattern=r'^accept:\d+$'))
    app.add_handler(CallbackQueryHandler(toggle, pattern=r'^toggle$'))
    app.add_handler(CommandHandler('admin', admin_cmd))
    app.add_handler(CallbackQueryHandler(admin_menu_callback, pattern=r'^admin:(workers|orders|announcements|payments|stats|payment_settings|broadcast|back)$'))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('workers', workers_cmd))
    app.add_handler(CommandHandler('orders', orders_cmd))
    app.add_handler(CommandHandler('announcements', announcements_cmd))
    app.add_handler(CommandHandler('payments', payments_cmd))
    app.add_handler(CommandHandler('stats', stats_cmd))
    app.add_handler(MessageHandler(filters.Regex(r'^👤 Менинг профилим$'), profile))
    app.add_handler(MessageHandler(filters.Regex(r'^🔧 Хизматлар$'), services))
    app.add_handler(MessageHandler(filters.Regex(r'^👨‍🔧 Устаман$'), worker_menu))
    app.add_handler(MessageHandler(filters.Regex(r'^Алоқа$'), contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generic_menu))
    return app


def main():
    init_database()
    app = build_application()
    logger.info('TEZ Service bot starting')
    if RENDER_EXTERNAL_URL:
        url = RENDER_EXTERNAL_URL.rstrip('/') + '/telegram/webhook'
        app.run_webhook(listen='0.0.0.0', port=PORT, url_path='telegram/webhook', webhook_url=url)
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
