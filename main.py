#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
from flask import Flask, request
import os
import threading
# aeroplane function steps { 
import math
import requests
from geopy.distance import distance  # pip install geopy (add to requirements)


# =============================================================================
# CONFIGURATION
# =============================================================================
BOT_TOKEN = "8616715853:AAGRGBya1TvbSzP2PVDN010-15IK6LVa114"
OWNER_ID = 6504476778

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

WEBHOOK_URL_PATH = "/webhook"

# =============================================================================
# BASIC COMMAND
# =============================================================================
@bot.message_handler(commands=['start'])
def start_command(message):
    """Welcome message"""
    bot.reply_to(message, "✅ Bot is working! Send /help for commands.")

# =============================================================================
# WEBHOOK ROUTES
# =============================================================================
@app.route(WEBHOOK_URL_PATH, methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

@app.route('/')
def home():
    return "✅ Bot is running (Basic)!"

# =============================================================================
# BOT STARTUP
# =============================================================================
def start_bot():
    bot.remove_webhook()
    webhook_url = f"https://mohyan-telegram-bot.onrender.com{WEBHOOK_URL_PATH}"
    bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook set to {webhook_url}")

if __name__ == "__main__":
    threading.Thread(target=start_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# =============================================================================
# AEROPLANE TRACKER MODULE – ADD THIS TO YOUR main.py
# (Kahin bhi daal sakte ho, preferably BOT COMMANDS section ke baad)
# ============================================================================  
  
# -------------------- CONFIG --------------------
OPENSKY_URL = "https://opensky-network.org/api/states/all"
MAP_WEBSITE = "https://your-map-site.onrender.com"  # Apna hosted map website (with ads)
CHECK_INTERVAL = 60  # seconds

# -------------------- DATABASE TABLE --------------------
# Add this to init_db() function
"""
c.execute('''CREATE TABLE IF NOT EXISTS tracking (
    user_id INTEGER PRIMARY KEY,
    lat REAL,
    lon REAL,
    range_km INTEGER,
    last_notified TEXT,
    created_at TIMESTAMP
)''')
"""

# -------------------- HELPER FUNCTIONS --------------------
def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two lat/lon points"""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_flights_in_bbox(lat, lon, radius_km):
    """Get flights from OpenSky within bounding box of given radius"""
    # Approximate degree to km: 1° lat ≈ 111 km, 1° lon varies with latitude
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    lamin = lat - lat_delta
    lamax = lat + lat_delta
    lomin = lon - lon_delta
    lomax = lon + lon_delta
    params = {
        'lamin': lamin,
        'lamax': lamax,
        'lomin': lomin,
        'lomax': lomax
    }
    try:
        resp = requests.get(OPENSKY_URL, params=params, timeout=10)
        data = resp.json()
        flights = []
        for state in data.get('states', []):
            # state[5] = longitude, state[6] = latitude
            if state[5] and state[6]:
                flight_lon = state[5]
                flight_lat = state[6]
                flights.append({
                    'icao24': state[0],
                    'callsign': state[1].strip() if state[1] else 'N/A',
                    'lat': flight_lat,
                    'lon': flight_lon,
                    'altitude': state[7],
                    'velocity': state[9],
                    'heading': state[10]
                })
        return flights
    except Exception as e:
        print(f"OpenSky error: {e}")
        return []

# -------------------- TRACKING SESSIONS --------------------
active_tracking = {}  # user_id -> {'lat':..., 'lon':..., 'range':..., 'last_notified': timestamp}
tracking_lock = threading.Lock()

def save_tracking(user_id, lat, lon, range_km):
    """Store tracking info in memory and database"""
    with tracking_lock:
        active_tracking[user_id] = {
            'lat': lat,
            'lon': lon,
            'range': range_km,
            'last_notified': None
        }
    # Also save to DB (optional, for persistence)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO tracking (user_id, lat, lon, range_km, created_at)
                     VALUES (?, ?, ?, ?, ?)''',
                  (user_id, lat, lon, range_km, datetime.datetime.now()))
        conn.commit()

def remove_tracking(user_id):
    with tracking_lock:
        active_tracking.pop(user_id, None)
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM tracking WHERE user_id=?", (user_id,))
        conn.commit()

def load_tracking_from_db():
    """Load all active tracking sessions from DB on startup"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, lat, lon, range_km FROM tracking")
        rows = c.fetchall()
        for row in rows:
            active_tracking[row['user_id']] = {
                'lat': row['lat'],
                'lon': row['lon'],
                'range': row['range_km'],
                'last_notified': None
            }
    print(f"✅ Loaded {len(active_tracking)} tracking sessions")

# -------------------- BACKGROUND CHECKER --------------------
def check_nearby_flights():
    """Background job: for each tracked user, find nearby flights and notify"""
    with tracking_lock:
        if not active_tracking:
            return
        # Copy to avoid modification during iteration
        users = list(active_tracking.items())
    
    for user_id, data in users:
        lat = data['lat']
        lon = data['lon']
        range_km = data['range']
        
        flights = get_flights_in_bbox(lat, lon, range_km)
        nearby = []
        for f in flights:
            dist = haversine(lat, lon, f['lat'], f['lon'])
            if dist <= range_km:
                nearby.append(f)
        
        if nearby:
            # Prepare notification
            msg = f"✈️ *Flight near you!*\n\n"
            for f in nearby[:3]:  # limit to 3 to avoid spam
                msg += f"• `{f['callsign']}` at {f['altitude']}m, {f['velocity']}m/s\n"
            if len(nearby) > 3:
                msg += f"... and {len(nearby)-3} more\n"
            msg += f"\n[📍 View on Map]({MAP_WEBSITE}?lat={lat}&lon={lon}&range={range_km})"
            
            try:
                bot.send_message(user_id, msg, parse_mode="Markdown")
                # Update last_notified time
                with tracking_lock:
                    if user_id in active_tracking:
                        active_tracking[user_id]['last_notified'] = datetime.datetime.now().isoformat()
            except Exception as e:
                print(f"Failed to notify {user_id}: {e}")

# Add this job to scheduler (in your existing scheduler)
# scheduler.add_job(check_nearby_flights, 'interval', seconds=CHECK_INTERVAL)

# -------------------- BOT COMMAND: /nearby --------------------
@bot.message_handler(commands=['nearby'])
def cmd_nearby(message):
    """Start airplane tracking by sharing location"""
    bot.reply_to(message, "📍 Please share your location to find nearby flights.",
                 reply_markup=types.ForceReply(selective=True))

@bot.message_handler(content_types=['location'])
def handle_location(message):
    """Receive location and ask for range"""
    lat = message.location.latitude
    lon = message.location.longitude
    # Store temporarily in user data (or use next step handler)
    bot.register_next_step_handler_by_chat_id(
        message.chat.id,
        lambda m: process_range_selection(m, lat, lon)
    )
    # Present range options
    markup = types.InlineKeyboardMarkup(row_width=3)
    ranges = [700, 20_000, 60_000, 140_000, 210_000, 339_000]  # meters
    for r in ranges:
        km = r//1000
        markup.add(types.InlineKeyboardButton(f"{km} km", callback_data=f"range_{r}"))
    bot.reply_to(message, "📏 Select range (in km):", reply_markup=markup)

def process_range_selection(message, lat, lon):
    # This is just a placeholder; actual range will come via callback
    pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('range_'))
def range_selected(call):
    """Save tracking session"""
    range_m = int(call.data.split('_')[1])
    range_km = range_m // 1000
    user_id = call.from_user.id
    lat = call.message.reply_to_message.location.latitude  # hacky, better to store in temp dict
    lon = call.message.reply_to_message.location.longitude
    save_tracking(user_id, lat, lon, range_km)
    bot.edit_message_text(
        f"✅ Tracking started! You'll be notified when a flight comes within {range_km} km.",
        call.message.chat.id,
        call.message.message_id
    )
    # Immediately check once
    check_nearby_flights()

@bot.message_handler(commands=['stop_tracking'])
def stop_tracking(message):
    """Stop tracking for this user"""
    remove_tracking(message.from_user.id)
    bot.reply_to(message, "⏹️ Tracking stopped.")
