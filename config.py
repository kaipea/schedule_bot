"""All configuration comes from environment variables (set them in Railway)."""
import os
from datetime import time
from zoneinfo import ZoneInfo


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour, minute, tzinfo=TZ)


# --- Telegram ---
TELEGRAM_TOKEN = _required("TELEGRAM_TOKEN")
# Leave unset on first deploy, message /whoami, then set it and redeploy.
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"]) if os.environ.get("TELEGRAM_CHAT_ID") else None

# --- Google Calendar (service account) ---
GOOGLE_SA_JSON = _required("GOOGLE_SERVICE_ACCOUNT_JSON")  # the full key JSON, pasted as one value
WRITE_CALENDAR_ID = _required("GOOGLE_CALENDAR_ID")  # usually your Gmail address
EXTRA_CALENDAR_IDS = [
    c.strip() for c in os.environ.get("GOOGLE_EXTRA_CALENDAR_IDS", "").split(",") if c.strip()
]
READ_CALENDAR_IDS = [WRITE_CALENDAR_ID] + EXTRA_CALENDAR_IDS

# --- Timing ---
TZ = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Asia/Singapore"))
DAILY_TIME = _clock(os.environ.get("DAILY_TIME", "07:30"))
WEEKLY_DAY = int(os.environ.get("WEEKLY_DAY", "0"))  # 0 = Monday ... 6 = Sunday

# --- Sharing ---
OWNER_NAME = os.environ.get("OWNER_NAME", "")  # shown in the header recipients see, e.g. "Wei Kai's week"

# --- Storage ---
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")  # mount a Railway volume at /app/data

# --- Claude (only used for free-text messages) ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
