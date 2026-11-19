from os import environ

API_ID = int(environ.get("API_ID", "12345678"))
API_HASH = environ.get("API_HASH", "your_api_hash_here")

# ==================== BOT TOKENS ====================
# Set the Telegram Bot Tokens below.
# If a token is left empty (""), that bot will simply be skipped.

TERABOX_BOT_TOKEN = environ.get("TERABOX_BOT_TOKEN", environ.get("BOT_TOKEN", ""))
INSTA_BOT_TOKEN = environ.get("INSTA_BOT_TOKEN", "")
THREADS_BOT_TOKEN = environ.get("THREADS_BOT_TOKEN", "")
PINTEREST_BOT_TOKEN = environ.get("PINTEREST_BOT_TOKEN", "")
KICK_BOT_TOKEN = environ.get("KICK_BOT_TOKEN", "")
TWITCH_BOT_TOKEN = environ.get("TWITCH_BOT_TOKEN", "")

# Legacy single bot token fallback
BOT_TOKEN = TERABOX_BOT_TOKEN

# Map of all purpose-specific bots
BOTS_CONFIG = {
    "terabox": {
        "name": "TeraBox Downloader",
        "token": TERABOX_BOT_TOKEN,
        "default_username": "teraboxdownloader_bot"
    },
    "instagram": {
        "name": "Instagram Downloader",
        "token": INSTA_BOT_TOKEN,
        "default_username": "instadownloader_bot"
    },
    "threads": {
        "name": "Threads Downloader",
        "token": THREADS_BOT_TOKEN,
        "default_username": "threadsdownloader_bot"
    },
    "pinterest": {
        "name": "Pinterest Downloader",
        "token": PINTEREST_BOT_TOKEN,
        "default_username": "pinterestdownloader_bot"
    },
    "kick": {
        "name": "Kick Downloader",
        "token": KICK_BOT_TOKEN,
        "default_username": "kickdownloader_bot"
    },
    "twitch": {
        "name": "Twitch Downloader",
        "token": TWITCH_BOT_TOKEN,
        "default_username": "twitchdownloader_bot"
    },
}

# REDIS
HOST = "localhost"  # redis host uri
PORT = 6379  # redis port
PASSWORD = ""  # redis password

PRIVATE_CHAT_ID = -1004161131573  # CHAT WHERE YOU WANT TO STORE VIDEOS
COOKIE = ""
ADMINS = [1317173146]

BOT_USERNAME = "teraboxdownloader_bot"

# Force Sub Channels
FORCE_SUB_ID_1 = -1003983694204
FORCE_SUB_ID_2 = -1004396922446
FORCE_SUB_ID_3 = -1004290277720

FORCE_LINK_1 = "https://t.me/..."
FORCE_LINK_2 = "https://t.me/..."
FORCE_LINK_3 = "https://t.me/..."

UPDATE_CHANNEL_URL = "https://t.me/..."

# Shortlink Ad System Configuration
SHORTLINK_API_URL = environ.get("SHORTLINK_API_URL", "https://vplink.in/api")
SHORTLINK_API_KEY = environ.get("SHORTLINK_API_KEY", "")

# Vercel API Details
TERABOX_API_BASE = "https://teraapi-six.vercel.app"
TERABOX_API_KEY = ""

# Social Media Downloader API Base (Cloudflare Worker API)
SOCIAL_API_BASE = environ.get("SOCIAL_API_BASE", "https://alldownloader.solankipriyanshu94.workers.dev")

# Database Configuration
MONGODB_URI = ""

# Token/Shortlink System Configuration
USE_TOKEN_SYSTEM = True
MIN_SHORTLINK_TIME = 60
