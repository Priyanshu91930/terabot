import asyncio
import logging
import time
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
                    UPDATE_CHANNEL_URL, MONGODB_URI, USE_TOKEN_SYSTEM)
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
        pattern=r"/start (?!token_)([0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12})",
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
        print(f"Recorded pending join request for user {user_id} in chat {chat_id}")
    except Exception as e:
        print(f"Error recording join request in Python: {e}")


# ------------------ LINK HANDLER ------------------

# Global Task Queue Variables
download_queue = []
is_processing = False

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
            await task["edit_message"].edit(
                f"⏳ **Your download is in queue.**\n\nPosition: `#{index + 1}`\n\nPlease wait, processing preceding files..."
            )
        except Exception:
            pass
            
    # Process the next task in background
    asyncio.create_task(run_task(next_task))

async def run_task(task):
    m = task["message"]
    url = task["url"]
    hm = task["edit_message"]
    
    try:
        await hm.edit("🚀 **Processing your request... Starting download.**")
        await process_download(m, url, hm)
    except Exception as e:
        log.exception(f"Error running queue task: {e}")
    finally:
        await trigger_next_in_queue()

async def process_download(m: Message, url: str, hm: Message):
    try:
        data = get_data(url)
    except Exception:
        await hm.edit("Sorry! API is dead or maybe your link is broken.")
        return
    if not data:
        await hm.edit("Sorry! API is dead or maybe your link is broken.")
        return
    db.set(m.sender_id, time.monotonic(), ex=60)

    # Folder: send all files one by one
    if isinstance(data, dict) and data.get("is_folder") and data.get("files"):
        files = data["files"]
        total = len(files)
        await hm.edit(f"📁 **Folder detected!** {total} files found. Starting download...\n\n__Powered by @TeraboxDownloaderINDIA__", parse_mode="markdown")

        for i, file_data in enumerate(files, 1):
            sizebytes = int(file_data.get("sizebytes", 0))
            if sizebytes > 524288000 and m.sender_id not in ADMINS:
                await m.reply(f"⏭️ Skipping **{file_data['file_name']}** (too big: {file_data['size']})")
                continue
            if sizebytes > 10737418240:
                await m.reply(f"⏭️ Skipping **{file_data['file_name']}** (too big: {file_data['size']})")
                continue

            status_msg = await m.reply(f"📥 **File {i}/{total}**: `{file_data['file_name']}`\n📦 Size: {file_data['size']}")
            sender = VideoSender(
                client=bot,
                data=file_data,
                message=m,
                edit_message=status_msg,
                url=url,
            )
            await sender.send_video()
            if sender.task:
                await sender.task
            await asyncio.sleep(1)

        await m.reply(f"✅ **All done!** {total} files processed.\n\n__Powered by @TeraboxDownloaderINDIA__", parse_mode="markdown")
        return

    # Single file
    if int(data["sizebytes"]) > 524288000 and m.sender_id not in ADMINS:
        await hm.edit(
            f"Sorry! File is too big.\n**I can download only 500MB and this file is of {data['size']}.**\nRather you can download this file from the link below:\n{url}",
            parse_mode="markdown",
        )
        return

    if int(data["sizebytes"]) > 10737418240 and m.sender_id in ADMINS:
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
    global is_processing, download_queue
    url = get_urls_from_string(m.text)
    if not url:
        return await m.reply("Please enter a valid url.")
        
    hm = await m.reply("Processing link...")
    
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
            
    shorturl = extract_code_from_url(url)
    if shorturl:
        fileid = db.get_key(shorturl)
        if fileid:
            uid = db.get_key(f"mid_{fileid}")
            if uid:
                check = await VideoSender.forward_file(
                    file_id=fileid, message=m, client=bot, edit_message=hm, uid=uid
                )
                if check:
                    return

    task_payload = {"message": m, "url": url, "edit_message": hm}
    
    if is_processing:
        download_queue.append(task_payload)
        position = len(download_queue)
        await hm.edit(
            f"⏳ **Your download is in queue.**\n\nPosition: `#{position}`\n\nPlease wait, processing preceding files..."
        )
    else:
        is_processing = True
        asyncio.create_task(run_task(task_payload))


# ------------------ START CLIENT ------------------

print("Bot is starting...")
bot.start(bot_token=BOT_TOKEN)
print("Bot started successfully! Listening for messages...")

bot.run_until_disconnected()

