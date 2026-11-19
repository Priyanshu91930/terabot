import re
import logging
from telethon import events
from telethon.tl.custom.message import Message

from modules.common import register_common_handlers, verify_user_access
from modules.social_engine import download_media_async, send_downloaded_media

log = logging.getLogger(__name__)

YOUTUBE_URL_REGEX = re.compile(
    r'(https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)[a-zA-Z0-9_\-]+(?:\S*)?)',
    re.IGNORECASE
)

WELCOME_TEXT = """
👋 **Welcome to YouTube Downloader Bot!** 🎥

Send me any **YouTube Video or Shorts link**, and I will download and send it to you in HD format! 🚀

📌 **Examples:**
• `https://youtu.be/xxxxxxxxxxx`
• `https://www.youtube.com/shorts/xxxxxxxxxxx`
• `https://www.youtube.com/watch?v=xxxxxxxxxxx`
"""

def register_youtube_bot(client):
    """Registers YouTube Downloader Bot handlers onto client."""
    register_common_handlers(client, "YouTube Downloader", WELCOME_TEXT)

    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text))
    async def youtube_link_handler(m: Message):
        text = m.text.strip()
        if text.startswith("/"):
            return

        match = YOUTUBE_URL_REGEX.search(text)
        if not match:
            if "instagram.com" in text or "threads." in text or "terabox" in text:
                return await m.reply("⚠️ This bot is for **YouTube** videos/shorts only. Please send a valid YouTube link.")
            return

        url = match.group(0)

        # Check Force Sub and Ad Token
        allowed = await verify_user_access(client, m, "YouTube")
        if not allowed:
            return

        status_msg = await m.reply("⏳ **Fetching YouTube Video... Please wait.**")
        try:
            res = await download_media_async(url, platform="youtube", status_msg=status_msg)
            if not res.get("success"):
                err = res.get("error", "Failed to extract YouTube video.")
                return await status_msg.edit(f"❌ **Download Failed:** `{err}`")

            await status_msg.edit("⬆️ **Uploading to Telegram...**")
            await send_downloaded_media(
                client=client,
                chat_id=m.chat_id,
                media_info=res,
                platform_name="YouTube",
                reply_to=m.id
            )
            await status_msg.delete()
        except Exception as e:
            log.error(f"[YouTubeBot] Error processing {url}: {e}")
            await status_msg.edit(f"❌ **Error:** `{e}`")
