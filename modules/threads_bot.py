import re
import logging
from telethon import events
from telethon.tl.custom.message import Message

from modules.common import register_common_handlers, verify_user_access
from modules.social_engine import download_media_async, send_downloaded_media

log = logging.getLogger(__name__)

THREADS_URL_REGEX = re.compile(r'https?://(?:www\.)?threads\.(?:net|com)/[a-zA-Z0-9_\-\.@/]+', re.IGNORECASE)

WELCOME_TEXT = """
👋 **Welcome to Threads Downloader Bot!** 🧵

Send me any **Threads post link**, and I will download the video or photo for you instantly! 🚀

📌 **Example:**
• `https://www.threads.net/@user/post/C3abc123...`
"""

def register_threads_bot(client):
    """Registers Threads Downloader Bot handlers onto client."""
    register_common_handlers(client, "Threads Downloader", WELCOME_TEXT)

    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text))
    async def threads_link_handler(m: Message):
        text = m.text.strip()
        if text.startswith("/"):
            return

        match = THREADS_URL_REGEX.search(text)
        if not match:
            if "instagram.com" in text or "pin.it" in text or "terabox" in text:
                return await m.reply("⚠️ This bot is for **Threads** links only. Please send a valid Threads URL.")
            return

        url = match.group(0)

        allowed = await verify_user_access(client, m, "Threads")
        if not allowed:
            return

        status_msg = await m.reply("⏳ **Fetching Threads media... Please wait.**")
        try:
            res = await download_media_async(url, platform="threads", status_msg=status_msg)
            if not res.get("success"):
                err = res.get("error", "Failed to extract media.")
                return await status_msg.edit(f"❌ **Download Failed:** `{err}`")

            await status_msg.edit("⬆️ **Uploading to Telegram...**")
            await send_downloaded_media(
                client=client,
                chat_id=m.chat_id,
                media_info=res,
                platform_name="Threads",
                reply_to=m.id
            )
            await status_msg.delete()
        except Exception as e:
            log.error(f"[ThreadsBot] Error processing {url}: {e}")
            await status_msg.edit(f"❌ **Error:** `{e}`")
