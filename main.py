#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
from telebot import types                    # <-- YEH IMPORT MISSING THA
from flask import Flask, request
import os
import threading
import math
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler  # <-- YEH ADD KARO

# =============================================================================
# CONFIGURATION
# =============================================================================
BOT_TOKEN = "8616715853:AAGRGBya1TvbSzP2PVDN010-15IK6LVa114"
OWNER_ID = 6504476778

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

WEBHOOK_URL_PATH = "/webhook"

# =============================================================================
# SCHEDULER SETUP
# =============================================================================
scheduler = BackgroundScheduler()
scheduler.start()

# =============================================================================
# BASIC COMMAND
# =============================================================================
@bot.message_handler(commands=['start'])
def start_command(message):
    bot.reply_to(message, "✅ Bot is working! Send /help for commands.")

# =============================================================================
# AEROPLANE TRACKER CONFIG
# =============================================================================
OPENSKY_URL = "https://opensky-network.org/api/states/all"
FLIGHT_UPDATE_INTERVAL = 10
FLIGHT_DURATION = 60

active_flight_tracking = {}
flight_tracking_lock = threading.Lock()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_flights_in_radius(lat, lon, radius_km):
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    params = {
        'lamin': lat - lat_delta,
        'lamax': lat + lat_delta,
        'lomin': lon - lon_delta,
        'lomax': lon + lon_delta
    }
    try:
        resp = requests.get(OPENSKY_URL, params=params, timeout=10)
        data = resp.json()
        flights = []
        for state in data.get('states', []):
            if state[5] and state[6]:
                flight_lon = state[5]
                flight_lat = state[6]
                dist = haversine(lat, lon, flight_lat, flight_lon)
                if dist <= radius_km:
                    flights.append({
                        'callsign': state[1].strip() if state[1] else 'Unknown',
                        'icao24': state[0],
                        'lat': flight_lat,
                        'lon': flight_lon,
                        'altitude': state[7] if state[7] else 0,
                        'velocity': state[9] if state[9] else 0,
                        'heading': state[10] if state[10] else 0,
                        'distance': round(dist, 1)
                    })
        return flights
    except Exception as e:
        print(f"OpenSky error: {e}")
        return []

def format_flight_message(flights, lat, lon, radius_km):
    if not flights:
        return f"✈️ *No flights found within {radius_km}km*\n\n_Will keep checking..._"
    msg = f"✈️ *Flights within {radius_km}km*\n━━━━━━━━━━━━━━━━━━━━━\n"
    for f in flights[:5]:
        msg += f"\n🛩️ *{f['callsign']}*\n"
        msg += f"   📍 Distance: `{f['distance']} km`\n"
        msg += f"   📈 Altitude: `{f['altitude']} m`\n"
        msg += f"   💨 Speed: `{f['velocity']} m/s`\n"
        if f['heading']:
            msg += f"   🧭 Heading: `{f['heading']}°`\n"
        msg += f"   🆔 ID: `{f['icao24']}`\n"
    if len(flights) > 5:
        msg += f"\n... and {len(flights)-5} more"
    msg += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"_Updates every 10s · Auto-stops in 60s_"
    return msg

def flight_updater_job():
    with flight_tracking_lock:
        now = datetime.now()
        expired = []
        for user_id, data in active_flight_tracking.items():
            if now > data['expires_at']:
                expired.append(user_id)
                continue
            flights = get_flights_in_radius(data['lat'], data['lon'], data['radius_km'])
            msg = format_flight_message(flights, data['lat'], data['lon'], data['radius_km'])
            try:
                bot.edit_message_text(
                    msg,
                    chat_id=data['chat_id'],
                    message_id=data['message_id'],
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Edit error for {user_id}: {e}")
        for uid in expired:
            del active_flight_tracking[uid]

# =============================================================================
# SCHEDULER JOB ADD
# =============================================================================
scheduler.add_job(flight_updater_job, 'interval', seconds=FLIGHT_UPDATE_INTERVAL)

# =============================================================================
# BOT COMMAND HANDLERS
# =============================================================================
@bot.message_handler(commands=['nearby_flight'])
def cmd_nearby_flight(message):
    with flight_tracking_lock:
        if message.from_user.id in active_flight_tracking:
            del active_flight_tracking[message.from_user.id]
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    location_btn = types.KeyboardButton("📍 Share Location", request_location=True)
    markup.add(location_btn)
    bot.reply_to(
        message,
        "📍 Please share your current location to find nearby flights.\n\n"
        "Or you can use the button below.",
        reply_markup=markup
    )

@bot.message_handler(content_types=['location'])
def handle_flight_location(message):
    lat = message.location.latitude
    lon = message.location.longitude
    markup = types.ReplyKeyboardRemove()
    bot.send_message(message.chat.id, "📍 Location received! Now select range.", reply_markup=markup)
    if not hasattr(bot, 'temp_flight_data'):
        bot.temp_flight_data = {}
    bot.temp_flight_data[message.from_user.id] = {'lat': lat, 'lon': lon}
    ranges = [700, 20000, 60000, 140000, 210000, 339000]
    markup = types.InlineKeyboardMarkup(row_width=2)
    for r in ranges:
        km = r // 1000
        markup.add(types.InlineKeyboardButton(f"{km} km", callback_data=f"flight_range_{r}"))
    bot.send_message(message.chat.id, "📏 Select search radius:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('flight_range_'))
def flight_range_selected(call):
    range_m = int(call.data.split('_')[2])
    radius_km = range_m / 1000
    user_id = call.from_user.id
    if not hasattr(bot, 'temp_flight_data') or user_id not in bot.temp_flight_data:
        bot.answer_callback_query(call.id, "❌ Session expired. Please start again.")
        return
    loc = bot.temp_flight_data[user_id]
    lat, lon = loc['lat'], loc['lon']
    del bot.temp_flight_data[user_id]
    flights = get_flights_in_radius(lat, lon, radius_km)
    msg = format_flight_message(flights, lat, lon, radius_km)
    sent = bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
    with flight_tracking_lock:
        active_flight_tracking[user_id] = {
            'lat': lat,
            'lon': lon,
            'radius_km': radius_km,
            'chat_id': call.message.chat.id,
            'message_id': sent.message_id,
            'start_time': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=FLIGHT_DURATION)
        }
    bot.answer_callback_query(call.id, "✅ Tracking started! Updates every 10s.")
    flight_updater_job()

@bot.message_handler(commands=['stop_tracking'])
def cmd_stop_tracking(message):
    with flight_tracking_lock:
        if message.from_user.id in active_flight_tracking:
            del active_flight_tracking[message.from_user.id]
            bot.reply_to(message, "⏹️ Flight tracking stopped.")
        else:
            bot.reply_to(message, "❌ No active tracking session.")

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
    return "✅ Bot is running!"

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
