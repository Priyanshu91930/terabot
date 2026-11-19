import os
import sys
import logging
import asyncio
from telethon.sync import TelegramClient

from config import API_ID, API_HASH, BOTS_CONFIG
from modules.common import auto_cleaner_task, StorageGuard
from modules.terabox_bot import register_terabox_bot
from modules.insta_bot import register_insta_bot
from modules.threads_bot import register_threads_bot
from modules.youtube_bot import register_youtube_bot
from modules.pinterest_bot import register_pinterest_bot
from modules.kick_bot import register_kick_bot
from modules.twitch_bot import register_twitch_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("MultiBotHub")

BOT_MODULE_MAP = {
    "terabox": register_terabox_bot,
    "instagram": register_insta_bot,
    "threads": register_threads_bot,
    "youtube": register_youtube_bot,
    "pinterest": register_pinterest_bot,
    "kick": register_kick_bot,
    "twitch": register_twitch_bot,
}


def start_all_bots():
    print("""
=====================================================
      🚀 MULTI-BOT HUB (SINGLE SCRIPT RUNNER) 🚀
=====================================================
    """)

    os.makedirs("bot_sessions", exist_ok=True)
    os.makedirs(os.path.join("downloads", "social"), exist_ok=True)

    active_clients = []

    for bot_key, cfg in BOTS_CONFIG.items():
        name = cfg.get("name", bot_key.title())
        token = (cfg.get("token") or "").strip()

        if not token:
            print(f"  [-] {name:<22} : SKIPPED (Token is empty in config.py)")
            continue

        register_func = BOT_MODULE_MAP.get(bot_key)
        if not register_func:
            log.warning(f"No module handler found for {bot_key}!")
            continue

        try:
            bot_id = token.split(":")[0] if ":" in token else bot_key
            session_path = os.path.join("bot_sessions", f"{bot_key}_{bot_id}")
            
            client = TelegramClient(session_path, API_ID, API_HASH)
            client.start(bot_token=token)
            
            me = client.get_me()
            client.bot_username = me.username
            client.bot_name = name

            # Register dedicated handlers for this bot
            register_func(client)

            active_clients.append(client)
            print(f"  [+] {name:<22} : ONLINE -> @{me.username} (ID: {me.id})")

        except Exception as e:
            log.error(f"Failed to start {name} ({bot_key}): {e}")

    if not active_clients:
        print("\n❌ Error: No bots could be started! Please configure at least one bot token in config.py.\n")
        return

    print(f"\n✅ Total {len(active_clients)} bot(s) running simultaneously in 1 process on VPS!")
    print(f"💾 Storage Guard Active: {StorageGuard.get_free_space_gb()} GB Free / {StorageGuard.get_total_space_gb()} GB Total")
    print("⚡ Listening for incoming Telegram messages concurrently...\n")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(auto_cleaner_task(), *(c.disconnected for c in active_clients)))


if __name__ == "__main__":
    start_all_bots()
