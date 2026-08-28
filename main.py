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
                    BOT_USERNAME, FORCE_LINK, MONGODB_URI)
from redis_db import db
from send_media import VideoSender
from terabox import get_data
from tools import (extract_code_from_url, get_urls_from_string, generate_shortenedUrl, 
                   is_user_on_chat, remove_all_videos)

bot = TelegramClient("main", API_ID, API_HASH)
log = logging.getLogger(__name__)


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
                Button.url(
                    "Website Source Code", url="https://github.com/r0ld3x/terabox-app"
                ),
                Button.url(
                    "Bot Source Code",
                    url="https://github.com/Priyanshu91930/terabot",
                ),
            ],
            [
                Button.url("Channel ", url="https://t.me/RoldexVerse"),
                Button.url("Group ", url="https://t.me/RoldexVerseChats"),
            ],
        ],
    )


@bot.on(
    events.NewMessage(
        pattern="/gen$",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def generate_token(m: Message):
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
    if m.sender_id not in ADMINS:
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
    uuid = m.pattern_match.group(1).strip()
    check_if = await is_user_on_chat(bot, FORCE_LINK, m.peer_id)
    if not check_if:
        return await m.reply(
            "You haven't joined @RoldexVerse or @RoldexVerseChats yet. Please join the channel and then send me the link again.\nThank you!",
            buttons=[
                [
                    Button.url("RoldexVerse", url="https://t.me/RoldexVerse"),
                    Button.url("RoldexVerseChats",
                               url="https://t.me/RoldexVerseChats"),
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
    asyncio.create_task(handle_message(m))


async def handle_message(m: Message):
    url = get_urls_from_string(m.text)
    if not url:
        return await m.reply("Please enter a valid url.")
    hm = await m.reply("Sending you the media wait...")
    is_spam = db.get(m.sender_id)
    if is_spam and m.sender_id not in ADMINS:
        ttl = db.ttl(m.sender_id)
        t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
        return await hm.edit(
            f"You are spamming.\n**Please wait {
                t.to_humanreadable()} and try again.**",
            parse_mode="markdown",
        )
    if_token_avl = db.get(f"active_{m.sender_id}")
    if not if_token_avl and m.sender_id not in ADMINS:
        return await hm.edit(
            "Your account is deactivated. send /gen to get activate it again."
        )
    shorturl = extract_code_from_url(url)
    if not shorturl:
        return await hm.edit("Seems like your link is invalid.")
    fileid = db.get_key(shorturl)
    if fileid:
        uid = db.get_key(f"mid_{fileid}")
        if uid:
            check = await VideoSender.forward_file(
                file_id=fileid, message=m, client=bot, edit_message=hm, uid=uid
            )
            if check:
                return
    try:
        data = get_data(url)
    except Exception:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")
    if not data:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")
    db.set(m.sender_id, time.monotonic(), ex=60)

    if int(data["sizebytes"]) > 524288000 and m.sender_id not in ADMINS:
        return await hm.edit(
            f"Sorry! File is too big.\n**I can download only 500MB and this file is of {
                data['size']}.**\nRather you can download this file from the link below:\n{url}",
            parse_mode="markdown",
        )

    sender = VideoSender(
        client=bot,
        data=data,
        message=m,
        edit_message=hm,
        url=url,
    )
    asyncio.create_task(sender.send_video())


# ------------------ START CLIENT ------------------

print("Bot is starting...")
bot.start(bot_token=BOT_TOKEN)
print("Bot started successfully! Listening for messages...")

bot.run_until_disconnected()
