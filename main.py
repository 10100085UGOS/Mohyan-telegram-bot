#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
from flask import Flask, request
import os
import threading

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
