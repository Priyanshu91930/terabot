from os import environ

API_ID = int(environ.get("API_ID", "27686895"))
API_HASH = environ.get("API_HASH", "0e996bd3891969ec5dfebf8bb3e39e94")
BOT_TOKEN = environ.get("BOT_TOKEN", "8811732867:AAGErBo5jt-18Hcyu2m9ydwoX9xNsl97QUk")  # bot token


# REDIS
HOST = "localhost"  # redis host uri
PORT = 6379  # redis port
PASSWORD = ""  # redis password

PRIVATE_CHAT_ID = -1004161131573  # CHAT WHERE YOU WANT TO STORE VIDEOS
# COOKIE FOR AUTHENTICATION (get from chrome dev tools) ex: "PANWEB=1; csrfToken=;
COOKIE = ""
ADMINS = [1317173146, 8494193109]


BOT_USERNAME = "teraboxdownloader2027_bot"

# Force user to join these channels. (make sure you have promoted the bot on these chats.)
# Put numeric IDs here for checking (e.g. -1002345678901)
FORCE_SUB_ID_1 = -1003983694204    # Channel 1 ID (Update this with your new Channel 1 ID)
FORCE_SUB_ID_2 = -1004396922446    # Channel 2 ID (Update this with your new Channel 2 ID)
FORCE_SUB_ID_3 = -1004290277720    # Group ID (Update this with your new Group ID)

# Invite Links for Buttons
FORCE_LINK_1 = "https://t.me/+exoDGnQTZwM0N2M1"
FORCE_LINK_2 = "https://t.me/+cySPj7iDogFkMzc1"
FORCE_LINK_3 = "https://t.me/+LaAHxuNGHgBmYmE1"

# Display URLs for buttons
UPDATE_CHANNEL_URL = "https://t.me/TeraboxDownloaderINDIA"

# Shortlink Ad System Configuration (VPLink / AdLinkFly)
SHORTLINK_API_URL = environ.get("SHORTLINK_API_URL", "https://vplink.in/api")
SHORTLINK_API_KEY = environ.get("SHORTLINK_API_KEY", "35591ad98834a002e1fe0b3b4acc6d84ef401782")
PUBLIC_EARN_API = SHORTLINK_API_KEY  # Backward compatibility alias

# Vercel API Details
TERABOX_API_BASE = "https://teraapi-six.vercel.app"
TERABOX_API_KEY = "AnihubTeraSecureKey2026_xYz"

# Database Configuration
MONGODB_URI = "mongodb+srv://anihubyt:Zxcvbnmm9193@cluster0.qv5tu12.mongodb.net/terabox_downloader?appName=Cluster0"

# Token/Shortlink System Configuration
USE_TOKEN_SYSTEM = False  # Set to True to force /gen ads shortlinks, or False to turn it off completely for direct downloads.



