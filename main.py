import asyncio
import logging
import time
import requests
from datetime import datetime
from pathlib import Path
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

import humanreadable as hr
from telethon import Button
from telethon.sync import TelegramClient, events
from telethon.tl.custom.message import Message
from telethon.types import UpdateNewMessage
from telethon.tl import types

from config import (ADMINS, API_HASH, API_ID, BOT_TOKEN, HOST, PASSWORD, PORT, 
                    BOT_USERNAME, FORCE_SUB_ID_1, FORCE_SUB_ID_2, FORCE_SUB_ID_3,
                    FORCE_LINK_1, FORCE_LINK_2, FORCE_LINK_3,
                    UPDATE_CHANNEL_URL, MONGODB_URI, USE_TOKEN_SYSTEM,
                    TERABOX_API_BASE, TERABOX_API_KEY)
from redis_db import db
from send_media import VideoSender
from terabox import get_data
from tools import (extract_code_from_url, get_urls_from_string, generate_shortenedUrl, 
                   is_user_on_chat, remove_all_videos)

bot = TelegramClient("main", API_ID, API_HASH)
log = logging.getLogger(__name__)


# ------------------ DYNAMIC SETTINGS RESOLVER ------------------

def is_token_system_enabled() -> bool:
    val = db.get("cfg_use_token_system")
    if val is not None:
        return val.decode("utf-8") == "True"
    return USE_TOKEN_SYSTEM

def is_force_sub_enabled() -> bool:
    val = db.get("cfg_use_force_sub")
    if val is not None:
        return val.decode("utf-8") == "True"
    return True # Enabled by default


# General debug logger for incoming private messages
@bot.on(events.NewMessage(incoming=True, outgoing=False, func=lambda x: x.is_private))
async def debug_incoming_messages(event):
    log.info(f"Received private message from {event.sender_id}: '{event.text}'")


# ------------------ SETTINGS COMMAND (ADMINS ONLY) ------------------

@bot.on(
    events.NewMessage(
        pattern="/settings$",
        incoming=True,
        outgoing=False,
        from_users=ADMINS,
    )
)
async def settings_menu(m: Message):
    token_status = "✅ Enabled" if is_token_system_enabled() else "❌ Disabled"
    forcesub_status = "✅ Enabled" if is_force_sub_enabled() else "❌ Disabled"
    
    text = f"""
⚙️ **Bot Admin Settings Panel**

Control bot features dynamically. Changes take effect instantly without restarting!

• **Token System (/gen & Ads)**: {token_status}
• **Force Join Subscription**: {forcesub_status}
• **Channel Target 1**: {FORCE_SUB_ID_1}
• **Channel Target 2**: {FORCE_SUB_ID_2}
• **Group Target 3**: {FORCE_SUB_ID_3}
"""
    await m.reply(
        text,
        parse_mode="markdown",
        buttons=[
            [
                Button.inline("Toggle Token System", data="toggle_token"),
            ],
            [
                Button.inline("Toggle Force Subscription", data="toggle_forcesub"),
            ],
            [
                Button.inline("Close Panel 🔒", data="close_settings"),
            ]
        ]
    )


@bot.on(events.CallbackQuery(pattern=r"(toggle_token|toggle_forcesub|close_settings)"))
async def settings_callback(event):
    if event.sender_id not in ADMINS:
        return await event.answer("You are not authorized to use this panel!", alert=True)
        
    data = event.data.decode("utf-8")
    
    if data == "close_settings":
        await event.delete()
        return await event.answer("Settings closed.")
        
    if data == "toggle_token":
        new_val = not is_token_system_enabled()
        db.set("cfg_use_token_system", "True" if new_val else "False")
        await event.answer(f"Token system set to {'Enabled' if new_val else 'Disabled'}", alert=True)
        
    elif data == "toggle_forcesub":
        new_val = not is_force_sub_enabled()
        db.set("cfg_use_force_sub", "True" if new_val else "False")
        await event.answer(f"Force Sub set to {'Enabled' if new_val else 'Disabled'}", alert=True)
        
    # Refresh the settings view
    token_status = "✅ Enabled" if is_token_system_enabled() else "❌ Disabled"
    forcesub_status = "✅ Enabled" if is_force_sub_enabled() else "❌ Disabled"
    
    text = f"""
⚙️ **Bot Admin Settings Panel**

Control bot features dynamically. Changes take effect instantly without restarting!

• **Token System (/gen & Ads)**: {token_status}
• **Force Join Subscription**: {forcesub_status}
• **Channel Target 1**: {FORCE_SUB_ID_1}
• **Channel Target 2**: {FORCE_SUB_ID_2}
• **Group Target 3**: {FORCE_SUB_ID_3}
"""
    await event.edit(
        text,
        parse_mode="markdown",
        buttons=[
            [
                Button.inline("Toggle Token System", data="toggle_token"),
            ],
            [
                Button.inline("Toggle Force Subscription", data="toggle_forcesub"),
            ],
            [
                Button.inline("Close Panel 🔒", data="close_settings"),
            ]
        ]
    )


# ------------------ COMMAND HANDLERS (from bot.py) ------------------

@bot.on(
    events.NewMessage(
        pattern="/start$",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def start(m: Message):
    reply_text = """
Hello there! I'm your friendly video downloader bot specially designed to fetch videos from Terabox. Share the Terabox link with me, and I'll swiftly get started on downloading it for you.

Let's make your video experience even better!
"""
    await m.reply(
        reply_text,
        link_preview=False,
        parse_mode="markdown",
        buttons=[
            [
                Button.url("Channel 1 📢", url=FORCE_LINK_1),
                Button.url("Channel 2 📢", url=FORCE_LINK_2),
            ],
            [
                Button.url("Group 💬", url=FORCE_LINK_3),
                Button.url("Update Channel 📢", url=UPDATE_CHANNEL_URL),
            ],
        ],
    )


@bot.on(
    events.NewMessage(
        pattern="/id",
        incoming=True,
    )
)
async def get_chat_id(m: Message):
    await m.reply(f"Chat ID: `{m.chat_id}`")


@bot.on(
    events.NewMessage(
        pattern="/gen$",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def generate_token(m: Message):
    if not is_token_system_enabled():
        return await m.reply("The token system is currently disabled. You can send links directly to download them!")
    is_user_active = db.get(f"active_{m.sender_id}")
    if is_user_active:
        ttl = db.ttl(f"active_{m.sender_id}")
        t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
        return await m.reply(
            f"""You are already active.
Your session will expire in {t.to_humanreadable()}."""
        )
    shortenedUrl = generate_shortenedUrl(m.sender_id)
    if not shortenedUrl:
        return await m.reply("Something went wrong. Please try again.")
    text = f"""
Hey {m.sender.first_name or m.sender.username}!

It seems like your Ads token has expired. Please refresh your token and try again.

Token Timeout: 1 hour

What is a token?
This is an Ads token. After viewing 1 ad, you can utilize the bot for the next 1 hour.

Keep the interactions going smoothly! 😊
"""

    await m.reply(
        text,
        link_preview=False,
        parse_mode="markdown",
        buttons=[Button.url("Click here To Refresh Token", url=shortenedUrl)],
    )


@bot.on(
    events.NewMessage(
        pattern=r"/start app_(.+)",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def start_app_link(m: Message):
    shortcode = m.pattern_match.group(1).strip()
    if shortcode.startswith("http"):
        url = shortcode
        shortcode = extract_code_from_url(url) or "app_link"
    else:
        url = f"https://1024terabox.com/s/{shortcode}"

    hm = await m.reply("📱 **Link received from App! Processing...**")

    try:
        data = get_data(url)
    except Exception:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")

    if not data:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")

    if isinstance(data, dict) and (data.get("error_type") == "MULTIPLE_FILES" or data.get("is_folder")):
        msg = data.get("error_message") or "This link contains multiple files or a folder. Please provide a link with a single file."
        return await hm.edit(f"⚠️ **Multiple Files / Folder Not Allowed**\n\n{msg}")

    import json
    db.set(f"req_url_{shortcode}", url, ex=86400)
    db.set(f"req_data_{shortcode}", json.dumps(data), ex=86400)

    file_name = data.get("file_name", "Unknown File")
    file_size = data.get("size", "N/A")

    text = f"""
📥 **File Details Found (via Mobile App)!**

📁 **Name**: `{file_name}`
📦 **Size**: `{file_size}`

👇 **How would you like to receive your file?**
"""
    await hm.edit(
        text,
        parse_mode="markdown",
        buttons=[
            [
                Button.inline("🎬 Video Format", data=f"dl_v_{shortcode}"),
                Button.inline("📁 Document / File", data=f"dl_d_{shortcode}"),
            ]
        ]
    )


@bot.on(
    events.NewMessage(
        pattern=r"/start (?!token_)(?!app_)([0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12})",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def start_ntoken(m: Message):
    if is_token_system_enabled() and m.sender_id not in ADMINS:
        if_token_avl = db.get(f"active_{m.sender_id}")
        if not if_token_avl:
            return await m.reply(
                "Your account is deactivated. send /gen to get activate it again."
            )
    text = m.pattern_match.group(1)
    fileid = db.get_key(str(text))
    if fileid:
        return await VideoSender.forward_file(
            file_id=fileid, message=m, client=bot, uid=text.strip()
        )
    else:
        return await m.reply("""your requested file is not available.""")


@bot.on(
    events.NewMessage(
        pattern=r"/start token_([0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12})",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def start_token(m: Message):
    if not is_token_system_enabled():
        return await m.reply("The token system is currently disabled. You can send links directly!")
    uuid = m.pattern_match.group(1).strip()
    if is_force_sub_enabled():
        check_1 = await is_user_on_chat(bot, FORCE_SUB_ID_1, m.peer_id)
        check_2 = await is_user_on_chat(bot, FORCE_SUB_ID_2, m.peer_id)
        check_3 = await is_user_on_chat(bot, FORCE_SUB_ID_3, m.peer_id)
        if not check_1 or not check_2 or not check_3:
            return await m.reply(
                "You haven't joined our channels and group yet. Please join all of them and then send me the link again.\nThank you!",
                buttons=[
                    [
                        Button.url("Join Channel 1 📢", url=FORCE_LINK_1),
                        Button.url("Join Channel 2 📢", url=FORCE_LINK_2),
                    ],
                    [
                        Button.url("Join Group 💬", url=FORCE_LINK_3),
                    ],
                    [
                        Button.url(
                            "ReCheck ♻️",
                            url=f"https://{BOT_USERNAME}.t.me?start={uuid}",
                        ),
                    ],
                ],
            )
    is_user_active = db.get(f"active_{m.sender_id}")
    if is_user_active:
        ttl = db.ttl(f"active_{m.sender_id}")
        t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
        return await m.reply(
            f"""You are already active.
Your session will expire in {t.to_humanreadable()}."""
        )
    if_token_avl = db.get(f"token_{uuid}")
    if not if_token_avl:
        return await generate_token(m)
    sender_id, shortenedUrl = if_token_avl.split("|")
    if m.sender_id != int(sender_id):
        return await m.reply(
            "Your token is invalid. Please try again.\n Hit /gen to get a new token."
        )
    set_user_active = db.set(f"active_{m.sender_id}", time.time(), ex=3600)
    db.delete(f"token_{uuid}")
    if set_user_active:
        return await m.reply("Your account is active. It will expire after 1 hour.")


@bot.on(
    events.NewMessage(
        pattern="/remove (.*)",
        incoming=True,
        outgoing=False,
        from_users=ADMINS,
    )
)
async def remove(m: UpdateNewMessage):
    user_id = m.pattern_match.group(1)
    if db.get(f"check_{user_id}"):
        db.delete(f"check_{user_id}")
        await m.reply(f"Removed {user_id} from the list.")
    else:
        await m.reply(f"{user_id} is not in the list.")


@bot.on(
    events.NewMessage(
        pattern="/removeall",
        incoming=True,
        outgoing=False,
        from_users=ADMINS,
    )
)
async def removeall(m: UpdateNewMessage):
    remove_all_videos()
    return await m.reply("Removed all videos from the list.")


# Handle pending join requests and save them in MongoDB (Join Request Mode support)
@bot.on(events.Raw(types.UpdateBotChatInviteRequester))
async def handle_raw_join_request(event):
    try:
        from pymongo import MongoClient
        
        user_id = event.user_id
        chat_id = event.peer.channel_id if hasattr(event.peer, 'channel_id') else event.peer.chat_id
        chat_id = int(f"-100{chat_id}")
        
        client = MongoClient(MONGODB_URI)
        db_mongo = client.get_default_database()
        if db_mongo is None or db_mongo.name == 'test':
            db_mongo = client['terabox_downloader']
            
        join_reqs = db_mongo['joinrequests']
        
        # Upsert pending join request to MongoDB
        join_reqs.update_one(
            {"userId": user_id, "chatId": chat_id},
            {"$set": {"status": "pending", "createdAt": datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        print(f"Error recording join request in Python: {e}")


# ------------------ ADMIN CUSTOM THUMBNAIL HANDLERS ------------------

@bot.on(
    events.NewMessage(
        pattern=r"^/(setthumb|set_thumb)",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def set_custom_thumbnail(m: Message):
    if m.sender_id not in ADMINS:
        return await m.reply("⚠️ **Permission Denied**: Only bot admins can set a custom thumbnail.")

    reply_msg = await m.get_reply_message()
    target_msg = reply_msg if reply_msg and reply_msg.photo else (m if m.photo else None)

    if not target_msg:
        return await m.reply(
            "🖼️ **How to set Custom Thumbnail:**\n\n"
            "1. Send a photo to the bot with caption `/setthumb`\n"
            "**OR**\n"
            "2. Reply to any photo with `/setthumb`"
        )

    hm = await m.reply("⏳ **Saving custom thumbnail...**")
    try:
        admin_thumb_path = os.path.join(os.getcwd(), "admin_thumb.jpg")
        await bot.download_media(target_msg.photo, file=admin_thumb_path)
        await hm.edit("✅ **Custom Thumbnail Saved Successfully!**\n\nAll future video and document downloads will use this thumbnail.")
    except Exception as e:
        log.error(f"Error saving custom thumbnail: {e}")
        await hm.edit(f"❌ **Failed to save thumbnail**: `{e}`")


@bot.on(
    events.NewMessage(
        pattern=r"^/(delthumb|removethumb)",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def delete_custom_thumbnail(m: Message):
    if m.sender_id not in ADMINS:
        return await m.reply("⚠️ **Permission Denied**: Only bot admins can delete custom thumbnails.")

    admin_thumb_path = os.path.join(os.getcwd(), "admin_thumb.jpg")
    if os.path.exists(admin_thumb_path):
        try:
            os.remove(admin_thumb_path)
            await m.reply("✅ **Custom Thumbnail Deleted.**\n\nBot will now use original Terabox thumbnails.")
        except Exception as e:
            await m.reply(f"❌ **Error deleting thumbnail**: `{e}`")
    else:
        await m.reply("ℹ️ **No custom thumbnail is currently set.**")


@bot.on(
    events.NewMessage(
        pattern=r"^/(showthumb|viewthumb)",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def show_custom_thumbnail(m: Message):
    if m.sender_id not in ADMINS:
        return await m.reply("⚠️ **Permission Denied**: Only bot admins can view custom thumbnail settings.")

    admin_thumb_path = os.path.join(os.getcwd(), "admin_thumb.jpg")
    if os.path.exists(admin_thumb_path):
        await m.reply(
            "🖼️ **Current Admin Custom Thumbnail:**",
            file=admin_thumb_path,
        )
    else:
        await m.reply("ℹ️ **No custom thumbnail is currently set.**\n\nSend a photo with `/setthumb` to set one.")


# ------------------ LINK HANDLER ------------------

# Global Task Queue & Pending Format Selection Variables
download_queue = []
is_processing = False
pending_download_requests = {}

async def trigger_next_in_queue():
    global is_processing, download_queue
    if len(download_queue) == 0:
        is_processing = False
        return
        
    next_task = download_queue.pop(0)
    is_processing = True
    
    # Update positions of remaining items in queue
    for index, task in enumerate(download_queue):
        try:
            fmt_name = "Document" if task.get("as_doc") else "Video"
            await task["edit_message"].edit(
                f"⏳ **Your download is in queue ({fmt_name}).**\n\nPosition: `#{index + 1}`\n\nPlease wait, processing preceding files..."
            )
        except Exception:
            pass
            
    # Process the next task in background
    asyncio.create_task(run_task(next_task))

async def run_task(task):
    m = task["message"]
    url = task["url"]
    hm = task["edit_message"]
    data = task.get("data")
    as_doc = task.get("as_doc", False)
    user_id = task.get("user_id")
    
    try:
        fmt_name = "Document" if as_doc else "Video"
        await hm.edit(f"🚀 **Processing your request... Starting download as {fmt_name}.**")
        await process_download(m, url, hm, data=data, as_doc=as_doc, user_id=user_id)
    except Exception as e:
        log.exception(f"Error running queue task: {e}")
    finally:
        await trigger_next_in_queue()

async def process_download(m: Message, url: str, hm: Message, data=None, as_doc: bool = False, user_id: int = None):
    if not data:
        try:
            data = get_data(url)
        except Exception:
            await hm.edit("Sorry! API is dead or maybe your link is broken.")
            return

    if not data:
        await hm.edit("Sorry! API is dead or maybe your link is broken.")
        return

    if isinstance(data, dict) and (data.get("error_type") == "MULTIPLE_FILES" or data.get("is_folder")):
        msg = data.get("error_message") or "This link contains multiple files or a folder. Please provide a link with a single file."
        await hm.edit(f"⚠️ **Multiple Files / Folder Not Allowed**\n\n{msg}")
        return

    effective_user_id = user_id or (m.sender_id if hasattr(m, "sender_id") else None)
    if effective_user_id:
        db.set(effective_user_id, time.monotonic(), ex=60)

    # Single file limits
    if int(data.get("sizebytes", 0)) > 524288000 and effective_user_id not in ADMINS:
        await hm.edit(
            f"Sorry! File is too big.\n**I can download only 500MB and this file is of {data.get('size', 'N/A')}.**\nRather you can download this file from the link below:\n{url}",
            parse_mode="markdown",
        )
        return

    if int(data.get("sizebytes", 0)) > 10737418240 and effective_user_id in ADMINS:
        await hm.edit(
            f"❌ **File Too Large**\n\nEven for admins, the limit is capped at **10.00 GB** to prevent VPS storage overload. This file is **{data['size']}**.",
            parse_mode="markdown"
        )
        return

    sender = VideoSender(
        client=bot,
        data=data,
        message=m,
        edit_message=hm,
        url=url,
        as_doc=as_doc,
        user_id=effective_user_id,
    )
    await sender.send_video()
    if sender.task:
        await sender.task


@bot.on(
    events.NewMessage(
        incoming=True,
        outgoing=False,
        func=lambda message: message.text
        and get_urls_from_string(message.text)
        and message.is_private,
    )
)
async def get_message(m: Message):
    global is_processing, download_queue, pending_download_requests
    url = get_urls_from_string(m.text)
    if not url:
        return await m.reply("Please enter a valid url.")
        
    hm = await m.reply("Fetching link details...")
    
    # 1. Force Sub check for direct link sending (if enabled and user is not admin)
    if is_force_sub_enabled() and m.sender_id not in ADMINS:
        check_1 = await is_user_on_chat(bot, FORCE_SUB_ID_1, m.sender_id)
        check_2 = await is_user_on_chat(bot, FORCE_SUB_ID_2, m.sender_id)
        check_3 = await is_user_on_chat(bot, FORCE_SUB_ID_3, m.sender_id)
        if not check_1 or not check_2 or not check_3:
            return await hm.edit(
                "❌ **Force Join Active**\n\nYou must join all our channels and group to download files! Please join all of them and then resend the link.",
                buttons=[
                    [
                        Button.url("Join Channel 1 📢", url=FORCE_LINK_1),
                        Button.url("Join Channel 2 📢", url=FORCE_LINK_2),
                    ],
                    [
                        Button.url("Join Group 💬", url=FORCE_LINK_3),
                    ]
                ]
            )
            
    is_spam = db.get(m.sender_id)
    if is_spam and m.sender_id not in ADMINS:
        ttl = db.ttl(m.sender_id)
        t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
        return await hm.edit(
            f"You are spamming.\n**Please wait {t.to_humanreadable()} and try again.**",
            parse_mode="markdown",
        )
        
    if is_token_system_enabled():
        if_token_avl = db.get(f"active_{m.sender_id}")
        if not if_token_avl and m.sender_id not in ADMINS:
            return await hm.edit(
                "Your account is deactivated. send /gen to get activate it again."
            )
            
    try:
        data = get_data(url)
    except Exception:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")

    if not data:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")

    if isinstance(data, dict) and (data.get("error_type") == "MULTIPLE_FILES" or data.get("is_folder")):
        msg = data.get("error_message") or "This link contains multiple files or a folder. Please provide a link with a single file."
        return await hm.edit(f"⚠️ **Multiple Files / Folder Not Allowed**\n\n{msg}")

    import json
    shorturl = extract_code_from_url(url)
    if not shorturl:
        from uuid import uuid4
        shorturl = str(uuid4())[:10]

    # Save original URL and parsed data in Redis with 24 hour expiry so callback works without duplicate API calls
    db.set(f"req_url_{shorturl}", url, ex=86400)
    db.set(f"req_data_{shorturl}", json.dumps(data), ex=86400)

    file_name = data.get("file_name", "Unknown File")
    file_size = data.get("size", "N/A")

    text = f"""
📥 **File Details Found!**

📁 **Name**: `{file_name}`
📦 **Size**: `{file_size}`

👇 **How would you like to receive your file?**
"""
    await hm.edit(
        text,
        parse_mode="markdown",
        buttons=[
            [
                Button.inline("🎬 Video Format", data=f"dl_v_{shorturl}"),
                Button.inline("📁 Document / File", data=f"dl_d_{shorturl}"),
            ]
        ]
    )


@bot.on(events.CallbackQuery(pattern=r"^dl_(v|d)_(.+)"))
async def download_format_callback(event):
    global is_processing, download_queue
    import json
    match = event.pattern_match
    fmt = match.group(1)
    if isinstance(fmt, bytes):
        fmt = fmt.decode("utf-8")

    shorturl = match.group(2)
    if isinstance(shorturl, bytes):
        shorturl = shorturl.decode("utf-8")
    shorturl = str(shorturl).strip()
    if shorturl.startswith("b'") and shorturl.endswith("'"):
        shorturl = shorturl[2:-1]

    as_doc = (fmt == "d")
    user_id = event.sender_id

    # Fetch original URL and cached file data from Redis
    raw_url = db.get(f"req_url_{shorturl}")
    if raw_url:
        url = raw_url.decode("utf-8") if isinstance(raw_url, bytes) else str(raw_url)
    else:
        url = f"https://1024terabox.com/s/{shorturl}"

    data = None
    raw_data = db.get(f"req_data_{shorturl}")
    if raw_data:
        try:
            data = json.loads(raw_data.decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data))
        except Exception:
            data = None

    hm = await event.get_message()
    fmt_name = "Document" if as_doc else "Video"

    # Immediately remove format selection buttons so user cannot double-click
    try:
        await hm.edit(f"🚀 **Starting download as {fmt_name}...**", buttons=None)
    except Exception:
        pass

    # Check fast-forward file cache first
    code = extract_code_from_url(url) or shorturl
    if code:
        fileid = db.get_key(code)
        if fileid:
            first_id = fileid.split(",")[0] if (isinstance(fileid, str) and "," in fileid) else fileid
            uid = db.get_key(f"mid_{fileid}") or db.get_key(f"mid_{first_id}") or code
            check = await VideoSender.forward_file(
                file_id=fileid, message=hm, client=bot, edit_message=hm, uid=uid, as_doc=as_doc
            )
            if check:
                return

    task_payload = {
        "message": hm,
        "user_id": user_id,
        "url": url,
        "data": data,
        "edit_message": hm,
        "as_doc": as_doc,
    }

    if is_processing:
        download_queue.append(task_payload)
        position = len(download_queue)
        try:
            await hm.edit(
                f"⏳ **Your download is in queue ({fmt_name}).**\n\nPosition: `#{position}`\n\nPlease wait, processing preceding files...",
                buttons=None
            )
        except Exception:
            pass
    else:
        is_processing = True
        asyncio.create_task(run_task(task_payload))


# ------------------ GROUP AUTO-REPLY HANDLER ------------------

group_cooldowns = {}

@bot.on(
    events.NewMessage(
        incoming=True,
        outgoing=False,
        func=lambda m: (m.is_group or m.is_channel) and m.text,
    )
)
async def group_mention_handler(m: Message):
    text_lower = m.text.lower()
    keywords = ["terabox", "bot", "download", "tera", BOT_USERNAME.lower()]
    
    if any(kw in text_lower for kw in keywords):
        chat_id = m.chat_id
        now = time.time()
        # Cooldown per group: reply at most once every 45 seconds per chat to avoid spam
        if chat_id in group_cooldowns and (now - group_cooldowns[chat_id]) < 45:
            return
            
        group_cooldowns[chat_id] = now
        start_url = f"https://t.me/{BOT_USERNAME}?start=true"
        reply_text = (
            "Hey there! 👋 I am here to help you download **TeraBox** files!\n\n"
            "Just click the button below to start me in PM and send your Terabox link! 🚀"
        )
        try:
            await m.reply(
                reply_text,
                parse_mode="markdown",
                buttons=[
                    [Button.url("Start Bot in PM 🚀", url=start_url)]
                ]
            )
        except Exception as e:
            log.warning(f"Failed to send group auto-reply: {e}")


# ------------------ START CLIENT ------------------

print("Bot is starting...")
bot.start(bot_token=BOT_TOKEN)
print("Bot started successfully! Listening for messages...")

bot.run_until_disconnected()

