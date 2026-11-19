import re
import logging
from telethon import events
from telethon.tl.custom.message import Message

from modules.common import register_common_handlers, verify_user_access
from modules.social_engine import download_media_async, send_downloaded_media

log = logging.getLogger(__name__)

INSTA_URL_REGEX = re.compile(r'https?://(?:www\.)?instagram\.com/(?:reel|p|tv|stories|share)/[a-zA-Z0-9_\-\./]+', re.IGNORECASE)

WELCOME_TEXT = """
👋 **Welcome to Instagram Downloader Bot!** 📸

Send me any **Instagram Reel, Post, Video, or Carousel link**, and I will download and send it to you instantly in high quality! 🚀

📌 **Examples:**
• `https://www.instagram.com/reel/C3abc123...`
• `https://www.instagram.com/p/C3xyz789...`
"""

def register_insta_bot(client):
    """Registers Instagram Downloader Bot handlers onto client."""
    register_common_handlers(client, "Instagram Downloader", WELCOME_TEXT)

    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text))
    async def insta_link_handler(m: Message):
        text = m.text.strip()
        if text.startswith("/"):
            return # Ignore commands

        match = INSTA_URL_REGEX.search(text)
        if not match:
            # Check if user sent a different link by accident
            if "threads.net" in text or "pin.it" in text or "terabox" in text:
                return await m.reply("⚠️ This bot is dedicated to **Instagram** links only. Please send a valid Instagram URL.")
            return

        url = match.group(0)

        # Verify Force Sub and Token Ads
        allowed = await verify_user_access(client, m, "Instagram")
        if not allowed:
            return

        status_msg = await m.reply("⏳ **Fetching Instagram Media... Please wait.**")
        try:
            res = await download_media_async(url, platform="instagram", status_msg=status_msg)
            if not res.get("success"):
                err = res.get("error", "Failed to extract media.")
                return await status_msg.edit(f"❌ **Download Failed:** `{err}`\n\nMake sure the account is public.")

            await status_msg.edit("⬆️ **Uploading to Telegram...**")
            await send_downloaded_media(
                client=client,
                chat_id=m.chat_id,
                media_info=res,
                platform_name="Instagram",
                reply_to=m.id
            )
            await status_msg.delete()
        except Exception as e:
            log.error(f"[InstaBot] Error processing {url}: {e}")
            await status_msg.edit(f"❌ **Error:** `{e}`")
