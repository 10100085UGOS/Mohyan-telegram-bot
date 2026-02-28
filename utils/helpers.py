from datetime import datetime, timedelta
from .database import get_db

OWNER_ID = OWNER_ID

def set_owner_id(oid):
    global OWNER_ID
    OWNER_ID = oid

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
