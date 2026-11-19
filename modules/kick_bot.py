import re
import logging
from telethon import events
from telethon.tl.custom.message import Message

from modules.common import register_common_handlers, verify_user_access
from modules.social_engine import download_media_async, send_downloaded_media

log = logging.getLogger(__name__)

KICK_URL_REGEX = re.compile(r'https?://(?:www\.)?kick\.com/[a-zA-Z0-9_\-\./]+', re.IGNORECASE)

WELCOME_TEXT = """
👋 **Welcome to Kick Downloader Bot!** 🟢

Send me any **Kick Clip or Video link**, and I will download and send it to you in MP4 format! 🚀

📌 **Example:**
• `https://kick.com/streamer?clip=clip_01HQ...`
"""

def register_kick_bot(client):
    """Registers Kick Downloader Bot handlers onto client."""
    register_common_handlers(client, "Kick Downloader", WELCOME_TEXT)

    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text))
    async def kick_link_handler(m: Message):
        text = m.text.strip()
        if text.startswith("/"):
            return

        match = KICK_URL_REGEX.search(text)
        if not match:
            if "twitch.tv" in text or "instagram.com" in text or "terabox" in text:
                return await m.reply("⚠️ This bot is for **Kick** clips only. Please send a valid Kick URL.")
            return

        url = match.group(0)

        allowed = await verify_user_access(client, m, "Kick")
        if not allowed:
            return

        status_msg = await m.reply("⏳ **Fetching Kick clip... Please wait.**")
        try:
            res = await download_media_async(url, platform="kick", status_msg=status_msg)
            if not res.get("success"):
                err = res.get("error", "Failed to extract clip.")
                return await status_msg.edit(f"❌ **Download Failed:** `{err}`")

            await status_msg.edit("⬆️ **Uploading to Telegram...**")
            await send_downloaded_media(
                client=client,
                chat_id=m.chat_id,
                media_info=res,
                platform_name="Kick",
                reply_to=m.id
            )
            await status_msg.delete()
        except Exception as e:
            log.error(f"[KickBot] Error processing {url}: {e}")
            await status_msg.edit(f"❌ **Error:** `{e}`")
