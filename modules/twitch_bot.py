import re
import logging
from telethon import events
from telethon.tl.custom.message import Message

from modules.common import register_common_handlers, verify_user_access
from modules.social_engine import download_media_async, send_downloaded_media

log = logging.getLogger(__name__)

TWITCH_URL_REGEX = re.compile(r'https?://(?:www\.|clips\.)?twitch\.tv/[a-zA-Z0-9_\-\./]+', re.IGNORECASE)

WELCOME_TEXT = """
👋 **Welcome to Twitch Downloader Bot!** 🟣

Send me any **Twitch Clip or Highlight link**, and I will download and send it directly in HD quality! 🚀

📌 **Examples:**
• `https://clips.twitch.tv/GloriousSavage...`
• `https://www.twitch.tv/streamer/clip/...`
"""

def register_twitch_bot(client):
    """Registers Twitch Downloader Bot handlers onto client."""
    register_common_handlers(client, "Twitch Downloader", WELCOME_TEXT)

    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text))
    async def twitch_link_handler(m: Message):
        text = m.text.strip()
        if text.startswith("/"):
            return

        match = TWITCH_URL_REGEX.search(text)
        if not match:
            if "kick.com" in text or "instagram.com" in text or "terabox" in text:
                return await m.reply("⚠️ This bot is for **Twitch** clips only. Please send a valid Twitch URL.")
            return

        url = match.group(0)

        allowed = await verify_user_access(client, m, "Twitch")
        if not allowed:
            return

        status_msg = await m.reply("⏳ **Fetching Twitch clip... Please wait.**")
        try:
            res = await download_media_async(url, platform="twitch", status_msg=status_msg)
            if not res.get("success"):
                err = res.get("error", "Failed to extract clip.")
                return await status_msg.edit(f"❌ **Download Failed:** `{err}`")

            await status_msg.edit("⬆️ **Uploading to Telegram...**")
            await send_downloaded_media(
                client=client,
                chat_id=m.chat_id,
                media_info=res,
                platform_name="Twitch",
                reply_to=m.id
            )
            await status_msg.delete()
        except Exception as e:
            log.error(f"[TwitchBot] Error processing {url}: {e}")
            await status_msg.edit(f"❌ **Error:** `{e}`")
