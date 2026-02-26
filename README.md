# 🤖 Premium Multi-Feature Telegram Bot

## Setup Instructions

### 1. Prerequisites
- Python 3.11+
- Telegram Bot Token (from @BotFather)
- Render.com account (for deployment)

### 2. Local Setup

```bash
# Clone or download the files
cd telegram-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BOT_TOKEN="your_bot_token_here"
export OWNER_ID="your_telegram_id"
export RENDER_URL="https://your-app.onrender.com"
export PORT=5000

# Run the bot
python main.py
```

### 3. Render Deployment

1. Create a new **Web Service** on [Render.com](https://render.com)
2. Connect your GitHub repo
3. Set these environment variables:
   - `BOT_TOKEN` = your bot token from @BotFather
   - `OWNER_ID` = your Telegram user ID
   - `RENDER_URL` = your Render app URL (e.g., `https://mybot.onrender.com`)
   - `PORT` = `5000`
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn main:app --bind 0.0.0.0:$PORT`

### 4. Features

| # | Feature | Command |
|---|---------|---------|
| 1 | Crypto Prices | `/btc`, `/eth`, `/doge` |
| 2 | Live Market | `/live` |
| 3 | BTC Chart | `/price_btc` |
| 4 | Price Alerts | `/alert BTC 65000` |
| 5 | Earn ReCOIN | `/getcoin` |
| 6 | Check Balance | `/balance` |
| 7 | Premium | `/premium` |
| 8 | Flight Tracker | `/nearby_flight` |
| 9 | Create Ads (Owner) | `/createad` |
| 10 | Manage Ads (Owner) | `/manageads` |
| 11 | Whitelist (Owner) | `/add_whitelist`, `/remove_whitelist`, `/list_whitelist` |

### 5. Database
SQLite database (`bot.db`) is auto-created on first run.

### ⚠️ Security
- **NEVER** hardcode your bot token in the code
- Use environment variables for all secrets
- Regenerate your token if it was ever exposed publicly
