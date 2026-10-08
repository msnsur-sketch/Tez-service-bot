import os
import re
import logging
from datetime import datetime, timezone, timedelta

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
SUBSCRIPTION_PRICE = 100
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
    '🔧 Сантехник', '⚡ Электрик', '📱 Телефон таъмири',
    '💻 Компьютер таъмири', '🧹 Уй тозалаш', '🪑 Мебель таъмири'
]
SERVICE_PATTERN = r'^(?:' + '|'.join(re.escape(x) for x in SERVICES) + r')$'

WORKER_COUNTRY, WORKER_CITY, WORKER_NAME, WORKER_PHONE, WORKER_SERVICE, WORKER_AREA, WORKER_PRICE = range(7)
ORDER_SERVICE, ORDER_NAME, ORDER_PHONE, ORDER_ADDRESS, ORDER_PROBLEM = range(10, 15)
ANN_COUNTRY, ANN_CITY, ANN_NAME, ANN_PHONE, ANN_SERVICE, ANN_ADDRESS, ANN_BUDGET, ANN_DETAILS = range(20, 28)
LOCATION_COUNTRY, LOCATION_CITY = range(40, 42)


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


def detect_city_from_text(text):
    s = normalize_text(text)
    if not s:
        return ''
    compact = s.replace(' ', '')
    for city in CITY_COUNTRY:
        if city in compact:
            return city
    return ''


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
            cur.execute('''CREATE TABLE IF NOT EXISTS workers (id SERIAL PRIMARY KEY,telegram_id BIGINT,name TEXT,phone TEXT,service TEXT,area TEXT,price TEXT,created_at TIMESTAMPTZ DEFAULT NOW())''')
            for c, d in [
                ('is_active','BOOLEAN DEFAULT TRUE'), ('country_code','TEXT'), ('country_name','TEXT'),
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
            cur.execute('''CREATE TABLE IF NOT EXISTS subscription_payments (
                id SERIAL PRIMARY KEY,
                worker_id INTEGER NOT NULL,
                telegram_id BIGINT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 100,
                currency TEXT NOT NULL DEFAULT 'сом',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                reviewed_by BIGINT
            )''')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_workers_tg ON workers(telegram_id)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')
            cur.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON subscription_payments(status)')
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
        ['🔧 Хизматлар','👨‍🔧 Уста чақириш'],
        ['📢 Эълон бериш','Алоқа'],
        ['👤 Менинг профилим'],
        ['🌍 Давлат/шаҳар']
    ], resize_keyboard=True)


def service_keyboard():
    return ReplyKeyboardMarkup([
        ['🔧 Сантехник','⚡ Электрик'],
        ['📱 Телефон таъмири','💻 Компьютер таъмири'],
        ['🧹 Уй тозалаш','🪑 Мебель таъмири'],
        ['⬅️ Бош меню']
    ], resize_keyboard=True)


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
    return '🔒 Бепул 7 та буюртма тугаган. 100 сомлик PRO обуна керак.'


def payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💳 Тўлов маълумоти', callback_data='payment:info')],
        [InlineKeyboardButton('✅ Тўладим', callback_data='payment:paid')]
    ])


async def send_payment_info(bot, chat_id):
    text = (
        f'💳 **Osh Service PRO**\n\n'
        f'💰 Нархи: {SUBSCRIPTION_PRICE} сом\n'
        f'📅 Муддати: {SUBSCRIPTION_DAYS} кун\n'
        f'♾️ Чексиз буюртма қабул қилиш\n\n'
        f'🏦 MBANK тўлов реквизити:\n{MBANK_PAYMENT_DETAILS}\n\n'
        f'Тўловни амалга оширгандан кейин «✅ Тўладим» тугмасини босинг.'
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown', reply_markup=payment_keyboard())


async def payment_start(update, context):
    await send_payment_info(context.bot, update.effective_user.id)


async def payment_callback(update, context):
    q = update.callback_query
    await q.answer()
    action = q.data.split(':', 1)[1]
    tg = q.from_user.id
    sub = get_worker_subscription(tg)
    if not sub:
        await q.message.reply_text('❗ Аввало уста сифатида рўйхатдан ўтинг.')
        return

    if action == 'info':
        await send_payment_info(context.bot, tg)
        return

    if action == 'paid':
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT id FROM subscription_payments
                               WHERE worker_id=%s AND status='pending'
                               ORDER BY id DESC LIMIT 1''', (sub['id'],))
                existing = cur.fetchone()
                if existing:
                    payment_id = existing[0]
                else:
                    cur.execute('''INSERT INTO subscription_payments(worker_id,telegram_id,amount,currency,status)
                                   VALUES(%s,%s,%s,'сом','pending') RETURNING id''',
                                (sub['id'], tg, SUBSCRIPTION_PRICE))
                    payment_id = cur.fetchone()[0]
                    cur.execute('UPDATE workers SET payment_pending=TRUE WHERE id=%s', (sub['id'],))
            conn.commit()
        finally:
            conn.close()

        await q.message.reply_text(
            f'✅ Тўлов сўровингиз қабул қилинди.\n\n🆔 Тўлов: #{payment_id}\n'
            '⏳ Администратор тўловни текшириб, обунани фаоллаштиради.'
        )
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(f'💳 ЯНГИ PRO ТЎЛОВ СЎРОВИ!\n\n'
                          f'🆔 Тўлов: #{payment_id}\n👨‍🔧 Уста: {tg}\n'
                          f'💰 Сумма: {SUBSCRIPTION_PRICE} сом\n\n'
                          f'Тўловни MBANK орқали текширинг.'),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton('✅ Тасдиқлаш', callback_data=f'payment_admin:approve:{payment_id}'),
                        InlineKeyboardButton('❌ Рад этиш', callback_data=f'payment_admin:reject:{payment_id}')
                    ]])
                )
            except Exception:
                logger.exception('admin payment notification failed')


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
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,worker_id,telegram_id,amount,status
                           FROM subscription_payments WHERE id=%s FOR UPDATE''', (payment_id,))
            p = cur.fetchone()
            if not p:
                await q.edit_message_text('❗ Тўлов сўрови топилмади.')
                return
            pid, worker_id, worker_tg, amount, status = p
            if status != 'pending':
                await q.edit_message_text(f'⚠️ Бу тўлов аллақачон кўриб чиқилган: {status}')
                return

            if action == 'approve':
                cur.execute('SELECT subscription_until FROM workers WHERE id=%s FOR UPDATE', (worker_id,))
                row = cur.fetchone()
                now = datetime.now(timezone.utc)
                old_until = row[0] if row else None
                start = old_until if old_until and old_until > now else now
                new_until = start + timedelta(days=SUBSCRIPTION_DAYS)
                cur.execute('''UPDATE workers SET subscription_until=%s,payment_pending=FALSE WHERE id=%s''', (new_until, worker_id))
                cur.execute('''UPDATE subscription_payments
                               SET status='approved',reviewed_at=NOW(),reviewed_by=%s WHERE id=%s''', (ADMIN_ID, payment_id))
                message = f'✅ Тўлов #{payment_id} тасдиқланди.\n\n♾️ PRO обуна {new_until.astimezone().strftime("%d.%m.%Y %H:%M")} гача фаол.'
            else:
                cur.execute('''UPDATE subscription_payments
                               SET status='rejected',reviewed_at=NOW(),reviewed_by=%s WHERE id=%s''', (ADMIN_ID, payment_id))
                cur.execute('UPDATE workers SET payment_pending=FALSE WHERE id=%s', (worker_id,))
                message = f'❌ Тўлов #{payment_id} рад этилди.\n\nАгар тўлов қилган бўлсангиз, администратор билан боғланинг.'
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
        logger.exception('worker payment result notification failed')


async def start(update, context):
    loc = get_location(update.effective_user.id)
    if not loc:
        await update.message.reply_text('🛠 Osh Service ботга хуш келибсиз!\n\n🌍 Аввало давлатни танланг:', reply_markup=country_keyboard())
        return LOCATION_COUNTRY
    await update.message.reply_text(
        f"🛠 Osh Service ботга хуш келибсиз!\n\n🌍 Давлат: {loc['country_name']}\n🏙 Шаҳар: {loc['city']}\n\nКеракли хизматни танланг:",
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
    await update.message.reply_text('🔧 Хизматни танланг:', reply_markup=service_keyboard())
    return WORKER_SERVICE


async def worker_service(update, context):
    if update.message.text not in SERVICES:
        await update.message.reply_text('❗ Хизматни тугма орқали танланг.', reply_markup=service_keyboard())
        return WORKER_SERVICE
    context.user_data['worker']['service'] = update.message.text
    await update.message.reply_text('📍 Ҳудудингизни ёзинг:')
    return WORKER_AREA


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
    buttons = [[InlineKeyboardButton('🔄 Фаол/нофаол', callback_data='toggle')]]
    if not sub or not sub['subscribed']:
        buttons.append([InlineKeyboardButton('💳 PRO — 100 сом/ой', callback_data='payment:info')])
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


async def order_address(update, context):
    address = update.message.text.strip()
    context.user_data['order']['address'] = address

    # Буюртма адресида аниқ шаҳар кўрсатилса, шу шаҳар устувор бўлади.
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

    # Агар адресда шаҳар аниқланган бўлса, буюртма шу шаҳарга юборилади.
    # Акс ҳолда мижоз профилидаги давлат/шаҳар ишлатилади.
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
                           FROM workers WHERE telegram_id IS NOT NULL AND COALESCE(is_active,TRUE)=TRUE ORDER BY id DESC''')
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
            cur.execute('''SELECT id,name,phone,country_code,country_name,city,COALESCE(is_active,TRUE)
                           FROM workers WHERE telegram_id=%s ORDER BY id DESC LIMIT 1''', (tg,))
            w = cur.fetchone()
            if not w:
                await q.edit_message_text('❗ Уста профили топилмади.')
                return
            wid,wname,wphone,wcc,wcn,wcity,wactive = w
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
                    '💳 Давом этиш учун ойига 100 сомлик PRO обуна керак.',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('💳 100 сом — PRO', callback_data='payment:info')]])
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
            extra = '\n\n🔒 Кейинги буюртмалар учун 100 сомлик PRO обуна керак.'
    await q.edit_message_text(
        f'✅ БУЮРТМА ҚАБУЛ ҚИЛИНДИ!\n\n👤 Мижоз: {cname}\n📞 Телефон: {cphone}\n'
        f'🔧 Хизмат: {service}\n📍 Манзил: {address}\n📝 Муаммо: {problem}{extra}'
    )
    try:
        await context.bot.send_message(chat_id=ctg, text=f'✅ Буюртмангиз қабул қилинди!\n\n👨‍🔧 Уста: {wname}\n📞 Телефон: {wphone}\n🔧 Хизмат: {service}\n📍 Шаҳар: {wcity}')
    except Exception:
        logger.exception('customer notification failed')


async def announcement_start(update, context):
    context.user_data['ann'] = {}
    await update.message.reply_text('🌍 Эълон учун давлатни танланг:', reply_markup=country_keyboard())
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
    if t == '⬅️ Бош меню':
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())
        return ConversationHandler.END
    if t == '✏️ Бошқа шаҳар':
        await update.message.reply_text('🏙 Шаҳар номини ёзинг:')
        return ANN_CITY
    context.user_data['ann']['city'] = t
    await update.message.reply_text('👤 Исмингизни ёзинг:')
    return ANN_NAME


async def ann_name(update, context):
    context.user_data['ann']['name'] = update.message.text.strip()
    await update.message.reply_text('📞 Телефон рақамингизни ёзинг:')
    return ANN_PHONE


async def ann_phone(update, context):
    p = update.message.text.strip()
    if len(re.sub(r'\D', '', p)) < 7:
        await update.message.reply_text('❗ Телефон рақами нотўғри.')
        return ANN_PHONE
    context.user_data['ann']['phone'] = p
    await update.message.reply_text('🔧 Хизматни танланг:', reply_markup=service_keyboard())
    return ANN_SERVICE


async def ann_service(update, context):
    if update.message.text not in SERVICES:
        await update.message.reply_text('❗ Хизматни тугма орқали танланг.', reply_markup=service_keyboard())
        return ANN_SERVICE
    context.user_data['ann']['service'] = update.message.text
    await update.message.reply_text('📍 Манзилни ёзинг:')
    return ANN_ADDRESS


async def ann_address(update, context):
    context.user_data['ann']['address'] = update.message.text.strip()
    await update.message.reply_text('💰 Бюджетингизни ёзинг:')
    return ANN_BUDGET


async def ann_budget(update, context):
    context.user_data['ann']['budget'] = update.message.text.strip()
    await update.message.reply_text('📝 Қўшимча маълумотни ёзинг:')
    return ANN_DETAILS


async def ann_details(update, context):
    a = context.user_data['ann']
    a['details'] = update.message.text.strip()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO announcements(telegram_id,name,phone,service,address,budget,details,country_code,country_name,city,currency)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                        (update.effective_user.id,a['name'],a['phone'],a['service'],a['address'],a['budget'],a['details'],a['country_code'],a['country_name'],a['city'],a['currency']))
            aid = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    await update.message.reply_text(
        f"✅ Эълонингиз қабул қилинди!\n\n🆔 #{aid}\n🌍 {a['country_name']}\n🏙 {a['city']}\n🔧 {a['service']}\n💰 {a['budget']}",
        reply_markup=main_keyboard()
    )
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(f"📢 ЯНГИ ЭЪЛОН!\n\n🆔 #{aid}\n👤 {a['name']}\n📞 {a['phone']}\n"
                      f"🌍 {a['country_name']}\n🏙 {a['city']}\n🔧 {a['service']}\n📍 {a['address']}\n"
                      f"💰 {a['budget']}\n📝 {a['details']}")
            )
        except Exception:
            logger.exception('admin announcement notification failed')
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


async def workers_cmd(update, context):
    if not admin_ok(update):
        await update.message.reply_text('❌ Рухсат йўқ.')
        return
    repair_old_workers()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT id,name,phone,service,country_name,city,price,COALESCE(is_active,TRUE),COALESCE(free_orders_used,0),subscription_until
                           FROM workers ORDER BY id DESC LIMIT 100''')
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        await update.message.reply_text('👨‍🔧 Усталар йўқ.')
        return
    out = ['👨‍🔧 УСТАЛАР:\n']
    for r in rows:
        sub = '♾️ PRO' if r[9] and r[9] > datetime.now(timezone.utc) else f'🎁 {r[8]}/{FREE_ORDER_LIMIT}'
        out.append(f'#{r[0]} {"🟢" if r[7] else "🔴"}\n👤 {r[1]}\n📞 {r[2]}\n🔧 {r[3]}\n🌍 {r[4] or "-"}\n🏙 {r[5] or "-"}\n💰 {r[6]}\n{sub}\n')
    await update.message.reply_text('\n'.join(out))


async def orders_cmd(update, context):
    if not admin_ok(update):
        await update.message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,name,phone,service,country_name,city,status,created_at FROM orders ORDER BY id DESC LIMIT 100')
            rows = cur.fetchall()
    finally:
        conn.close()
    await update.message.reply_text('\n'.join([
        f'#{r[0]} — {r[6]}\n👤 {r[1]}\n📞 {r[2]}\n🔧 {r[3]}\n🌍 {r[4] or "-"}\n🏙 {r[5] or "-"}\n🕐 {r[7]}\n' for r in rows
    ]) or '🔔 Буюртмалар йўқ.')


async def announcements_cmd(update, context):
    if not admin_ok(update):
        await update.message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id,name,phone,service,country_name,city,budget,details,created_at FROM announcements ORDER BY id DESC LIMIT 100')
            rows = cur.fetchall()
    finally:
        conn.close()
    await update.message.reply_text('\n'.join([
        f'#{r[0]}\n👤 {r[1]}\n📞 {r[2]}\n🔧 {r[3]}\n🌍 {r[4] or "-"}\n🏙 {r[5] or "-"}\n💰 {r[6]}\n📝 {r[7]}\n🕐 {r[8]}\n' for r in rows
    ]) or '📢 Эълонлар йўқ.')


async def payments_cmd(update, context):
    if not admin_ok(update):
        await update.message.reply_text('❌ Рухсат йўқ.')
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT p.id,p.worker_id,p.telegram_id,p.amount,p.currency,p.status,p.created_at,w.name
                           FROM subscription_payments p LEFT JOIN workers w ON w.id=p.worker_id
                           ORDER BY p.id DESC LIMIT 50''')
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        await update.message.reply_text('💳 Тўловлар йўқ.')
        return
    out = ['💳 PRO ТЎЛОВЛАР:\n']
    for r in rows:
        out.append(f'#{r[0]} — {r[5]}\n👨‍🔧 {r[7] or "-"}\n🆔 {r[2]}\n💰 {r[3]} {r[4]}\n🕐 {r[6]}\n')
    await update.message.reply_text('\n'.join(out))


async def stats_cmd(update, context):
    if not admin_ok(update):
        await update.message.reply_text('❌ Рухсат йўқ.')
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
    await update.message.reply_text(
        f'📊 СТАТИСТИКА\n\n👨‍🔧 Жами усталар: {w}\n🟢 Фаол усталар: {aw}\n'
        f'♾️ PRO усталар: {pro}\n🔔 Буюртмалар: {o}\n📢 Эълонлар: {a}\n💳 Кутилаётган тўловлар: {pp}'
    )


async def contact(update, context):
    await update.message.reply_text('📞 Алоқа\n\nOsh Service\nTelegram орқали биз билан боғланишингиз мумкин.')


async def worker_menu(update, context):
    await update.message.reply_text('👨‍🔧 Уста бўлими:', reply_markup=worker_menu_keyboard())


async def generic_menu(update, context):
    t = update.message.text
    if t == '⬅️ Бош меню':
        await update.message.reply_text('🏠 Бош меню', reply_markup=main_keyboard())


def build_application():
    app = Application.builder().token(BOT_TOKEN).build()

    loc = ConversationHandler(
        entry_points=[CommandHandler('start', start), MessageHandler(filters.Regex(r'^🌍 Давлат/шаҳар$'), location_menu_start)],
        states={
            LOCATION_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_country)],
            LOCATION_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_city)]
        },
        fallbacks=[CommandHandler('start', start)], allow_reentry=True
    )
    worker = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^👨‍🔧 Уста бўлиб рўйхатдан ўтиш$'), worker_start)],
        states={
            WORKER_COUNTRY:[MessageHandler(filters.TEXT & ~filters.COMMAND,worker_country)],
            WORKER_CITY:[MessageHandler(filters.TEXT & ~filters.COMMAND,worker_city)],
            WORKER_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,worker_name)],
            WORKER_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND,worker_phone)],
            WORKER_SERVICE:[MessageHandler(filters.Regex(SERVICE_PATTERN),worker_service)],
            WORKER_AREA:[MessageHandler(filters.TEXT & ~filters.COMMAND,worker_area)],
            WORKER_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND,worker_price)]
        },
        fallbacks=[CommandHandler('start',start)]
    )
    order = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(SERVICE_PATTERN), order_service)],
        states={
            ORDER_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,order_name)],
            ORDER_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND,order_phone)],
            ORDER_ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND,order_address)],
            ORDER_PROBLEM:[MessageHandler(filters.TEXT & ~filters.COMMAND,order_problem)]
        },
        fallbacks=[CommandHandler('start',start)]
    )
    ann = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^📢 Эълон бериш$'), announcement_start)],
        states={
            ANN_COUNTRY:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_country)],
            ANN_CITY:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_city)],
            ANN_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_name)],
            ANN_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_phone)],
            ANN_SERVICE:[MessageHandler(filters.Regex(SERVICE_PATTERN),ann_service)],
            ANN_ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_address)],
            ANN_BUDGET:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_budget)],
            ANN_DETAILS:[MessageHandler(filters.TEXT & ~filters.COMMAND,ann_details)]
        },
        fallbacks=[CommandHandler('start',start)]
    )

    app.add_handler(loc)
    app.add_handler(worker)
    app.add_handler(ann)
    app.add_handler(order)
    app.add_handler(CallbackQueryHandler(admin_payment_callback, pattern=r'^payment_admin:(approve|reject):\d+$'))
    app.add_handler(CallbackQueryHandler(payment_callback, pattern=r'^payment:(info|paid)$'))
    app.add_handler(CallbackQueryHandler(accept_order, pattern=r'^accept:\d+$'))
    app.add_handler(CallbackQueryHandler(toggle, pattern=r'^toggle$'))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('workers', workers_cmd))
    app.add_handler(CommandHandler('orders', orders_cmd))
    app.add_handler(CommandHandler('announcements', announcements_cmd))
    app.add_handler(CommandHandler('payments', payments_cmd))
    app.add_handler(CommandHandler('stats', stats_cmd))
    app.add_handler(MessageHandler(filters.Regex(r'^👤 Менинг профилим$'), profile))
    app.add_handler(MessageHandler(filters.Regex(r'^🔧 Хизматлар$'), services))
    app.add_handler(MessageHandler(filters.Regex(r'^👨‍🔧 Уста чақириш$'), worker_menu))
    app.add_handler(MessageHandler(filters.Regex(r'^Алоқа$'), contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generic_menu))
    return app


def main():
    init_database()
    app = build_application()
    logger.info('Osh Service bot starting')
    if RENDER_EXTERNAL_URL:
        url = RENDER_EXTERNAL_URL.rstrip('/') + '/telegram/webhook'
        app.run_webhook(listen='0.0.0.0', port=PORT, url_path='telegram/webhook', webhook_url=url)
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
