import re
import logging
from telethon import events
from telethon.tl.custom.message import Message

from modules.common import register_common_handlers, verify_user_access
from modules.social_engine import download_media_async, send_downloaded_media

log = logging.getLogger(__name__)

PINTEREST_URL_REGEX = re.compile(r'https?://(?:[a-zA-Z0-9_\-\.]+\.)?(?:pinterest\.(?:com|co|ca|de|fr|it|co\.uk|jp)|pin\.it)/[a-zA-Z0-9_\-\./]+', re.IGNORECASE)

WELCOME_TEXT = """
👋 **Welcome to Pinterest Downloader Bot!** 📌

Send me any **Pinterest Video, Pin, or Image link**, and I will download it in original resolution! 🚀

📌 **Examples:**
• `https://pin.it/7xYz123`
• `https://www.pinterest.com/pin/1234567890/`
"""

def register_pinterest_bot(client):
    """Registers Pinterest Downloader Bot handlers onto client."""
    register_common_handlers(client, "Pinterest Downloader", WELCOME_TEXT)

    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text))
    async def pinterest_link_handler(m: Message):
        text = m.text.strip()
        if text.startswith("/"):
            return

        match = PINTEREST_URL_REGEX.search(text)
        if not match:
            if "instagram.com" in text or "threads.net" in text or "terabox" in text:
                return await m.reply("⚠️ This bot is for **Pinterest** links only. Please send a valid Pinterest URL.")
            return

        url = match.group(0)

        allowed = await verify_user_access(client, m, "Pinterest")
        if not allowed:
            return

        status_msg = await m.reply("⏳ **Fetching Pinterest pin... Please wait.**")
        try:
            res = await download_media_async(url, platform="pinterest", status_msg=status_msg)
            if not res.get("success"):
                err = res.get("error", "Failed to extract media.")
                return await status_msg.edit(f"❌ **Download Failed:** `{err}`")

            await status_msg.edit("⬆️ **Uploading to Telegram...**")
            await send_downloaded_media(
                client=client,
                chat_id=m.chat_id,
                media_info=res,
                platform_name="Pinterest",
                reply_to=m.id
            )
            await status_msg.delete()
        except Exception as e:
            log.error(f"[PinterestBot] Error processing {url}: {e}")
            await status_msg.edit(f"❌ **Error:** `{e}`")
