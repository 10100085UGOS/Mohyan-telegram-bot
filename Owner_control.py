# =============================================================================
# OWNER CONTROLS MODULE
# =============================================================================
# Yeh file owner ke special commands handle karti hai.
# Har command ke upar comment diya hai ki wo kya karta hai.

from main import bot, OWNER_ID, get_db, add_coins, deduct_coins, set_premium
from telebot import types
import sqlite3
import time
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# Helper function: Owner check
# -----------------------------------------------------------------------------
def is_owner(user_id):
    """Check karta hai ki user owner hai ya nahi"""
    return user_id == OWNER_ID

# -----------------------------------------------------------------------------
# Command: /givecoin @username amount
# -----------------------------------------------------------------------------
# Ye command kisi bhi user ko ReCOIN de sakta hai (sirf owner).
# Example: /givecoin @mohyan 50
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
        # Find user by username (case insensitive)
        row = conn.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if row:
            add_coins(row['user_id'], amount)
            bot.reply_to(message, f"✅ {amount} ReCOIN @{username} ko de diye gaye!")
        else:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# -----------------------------------------------------------------------------
# Command: /removecoin @username amount
# -----------------------------------------------------------------------------
# Ye command kisi user ke ReCOIN kam kar sakta hai (sirf owner).
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
            # Deduct coins (agar balance kam ho to bhi deduct ho jayega, negative ho sakta hai)
            conn.execute("UPDATE user_coins SET balance = balance - ? WHERE user_id = ?", (amount, row['user_id']))
            conn.commit()
            bot.reply_to(message, f"✅ {amount} ReCOIN @{username} se kaat liye gaye.")
        else:
            bot.reply_to(message, f"❌ User @{username} nahi mila.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# -----------------------------------------------------------------------------
# Command: /setpremium @username days
# -----------------------------------------------------------------------------
# Ye command kisi user ko premium bana sakta hai (sirf owner).
# Example: /setpremium @mohyan 30   (30 din ke liye premium)
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

# -----------------------------------------------------------------------------
# Command: /removepremium @username
# -----------------------------------------------------------------------------
# Ye command kisi user ka premium hata sakta hai.
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

# -----------------------------------------------------------------------------
# Command: /block @username
# -----------------------------------------------------------------------------
# Ye command kisi user ko block kar deta hai (wo bot use nahi kar payega).
# NOTE: Iske liye aapko users table mein 'blocked' column banana hoga.
# Pehle ye column add karo: ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0;
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
        # Check if column exists, if not then create it (optional)
        conn.execute("PRAGMA table_info(users)").fetchall()
        # Actually, better to ensure column exists in init_db, but for now we'll try:
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

# -----------------------------------------------------------------------------
# Command: /unblock @username
# -----------------------------------------------------------------------------
# Ye command kisi user ka block hata deta hai.
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

# -----------------------------------------------------------------------------
# Command: /ban @username
# -----------------------------------------------------------------------------
# Ye command user ko permanently ban kar sakta hai (alag se ban table bana sakte ho ya same blocked use karo).
# Yahan hum same 'blocked' column use kar rahe hain, lekin aap chahe to alag 'banned' column bana sakte ho.
@bot.message_handler(commands=['ban'])
def ban_user(message):
    # Same as block for now, but you can add more logic
    block_user(message)  # Reuse block function

@bot.message_handler(commands=['unban'])
def unban_user(message):
    unblock_user(message)

# -----------------------------------------------------------------------------
# Command: /broadcast
# -----------------------------------------------------------------------------
# Ye command sabhi users ko message broadcast karta hai (sirf owner).
# Format: /broadcast Hello everyone!
@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    if not is_owner(message.from_user.id):
        return
    
    # Message ka text command ke baad ka part
    broadcast_text = message.text.replace('/broadcast', '', 1).strip()
    if not broadcast_text:
        bot.reply_to(message, "❌ Broadcast message likho.")
        return
    
    # Sabhi users ke IDs le lo
    conn = get_db()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    
    success = 0
    fail = 0
    for user in users:
        try:
            bot.send_message(user['user_id'], f"📢 **BROADCAST**\n\n{broadcast_text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.05)  # Thoda delay to avoid flood
        except:
            fail += 1
    
    bot.reply_to(message, f"✅ Broadcast complete.\n✓ Sent: {success}\n✗ Failed: {fail}")

# -----------------------------------------------------------------------------
# Command: /stats
# -----------------------------------------------------------------------------
# Ye command bot ke statistics dikhata hai (total users, premium users, etc.)
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

# -----------------------------------------------------------------------------
# Command: /userinfo @username
# -----------------------------------------------------------------------------
# Ye command kisi user ki details dikhata hai (balance, premium status, etc.)
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

# -----------------------------------------------------------------------------
# Command: /resetuser @username
# -----------------------------------------------------------------------------
# Ye command user ka data reset kar sakta hai (balance zero, premium hataye, etc.)
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
        # Reset balance to 0
        conn.execute("UPDATE user_coins SET balance = 0 WHERE user_id = ?", (user_id,))
        # Remove premium
        conn.execute("UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?", (user_id,))
        # Delete alerts (optional)
        conn.execute("DELETE FROM alerts WHERE user_id = ?", (user_id,))
        # Delete ad_views (optional)
        conn.execute("DELETE FROM ad_views WHERE user_id = ?", (user_id,))
        # Delete links (optional) – careful, unke links bhi delete ho jayenge
        # conn.execute("DELETE FROM links WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"✅ @{username} ka data reset kar diya gaya (balance 0, premium hata diya).")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# -----------------------------------------------------------------------------
# Owner Panel with Inline Buttons (Optional)
# -----------------------------------------------------------------------------
# Aap chahe to ek inline keyboard bana sakte ho jisse owner easily controls access kar sake.
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

# Inline button callbacks
@bot.callback_query_handler(func=lambda call: call.data.startswith('owner_'))
def owner_panel_callback(call):
    if not is_owner(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Owner only!")
        return
    
    action = call.data.split('_')[1]
    
    if action == "stats":
        # Simulate /stats
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
