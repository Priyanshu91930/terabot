import os
import time
import json
import logging
import asyncio
from contextlib import suppress
from datetime import datetime
import humanreadable as hr
from telethon import Button, events
from telethon.tl.custom.message import Message
from telethon.tl import types

from config import (ADMINS, FORCE_SUB_ID_1, FORCE_SUB_ID_2, FORCE_SUB_ID_3,
                    FORCE_LINK_1, FORCE_LINK_2, FORCE_LINK_3,
                    UPDATE_CHANNEL_URL, MONGODB_URI)
from redis_db import db
from send_media import VideoSender
from terabox import get_data
from tools import extract_code_from_url, get_urls_from_string, remove_all_videos, is_user_on_chat
from modules.common import (register_common_handlers, is_token_system_enabled, 
                            is_force_sub_enabled, verify_user_access)

log = logging.getLogger(__name__)

WELCOME_TEXT = """
Hello there! I'm your friendly video downloader bot specially designed to fetch videos from **Terabox**. 🚀

Share any Terabox link with me, and I'll swiftly download and send it to you!

Let's make your video experience even better!
"""

download_queue = []
is_processing = False
cached_loading_media = None


async def trigger_next_in_queue(client):
    global is_processing, download_queue
    if len(download_queue) == 0:
        is_processing = False
        return
        
    next_task = download_queue.pop(0)
    is_processing = True
    
    for index, task in enumerate(download_queue):
        try:
            fmt_name = "Document" if task.get("as_doc") else "Video"
            task_data = task.get("data") or {}
            fname = task_data.get("file_name", "File")
            await task["edit_message"].edit(
                f"⏳ **In Download Queue ({fmt_name})**\n\n"
                f"📁 **File:** `{fname}`\n"
                f"🔢 **Updated Queue Position:** `#{index + 1}`\n\n"
                f"Please wait, your turn is coming up!"
            )
        except Exception:
            pass
            
    asyncio.create_task(run_task(client, next_task))


async def run_task(client, task):
    m = task["message"]
    url = task["url"]
    hm = task["edit_message"]
    data = task.get("data")
    as_doc = task.get("as_doc", False)
    user_id = task.get("user_id")
    loading_msg = task.get("loading_msg")
    
    try:
        if loading_msg:
            with suppress(Exception):
                await loading_msg.delete()
        fmt_name = "Document" if as_doc else "Video"
        fname = data.get("file_name", "File") if data else "File"
        with suppress(Exception):
            await hm.edit(
                f"🚀 **Your Turn Arrived!**\n\n"
                f"📁 **File:** `{fname}`\n"
                f"⚡ **Starting download as {fmt_name}...**"
            )
        from modules.common import GLOBAL_DOWNLOAD_SEMAPHORE
        async with GLOBAL_DOWNLOAD_SEMAPHORE:
            await process_download(client, m, url, hm, data=data, as_doc=as_doc, user_id=user_id)
    except Exception as e:
        log.exception(f"Error running queue task: {e}")
    finally:
        await trigger_next_in_queue(client)


async def process_download(client, m: Message, url: str, hm: Message, data=None, as_doc: bool = False, user_id: int = None):
    if not data:
        try:
            data = get_data(url)
        except Exception:
            with suppress(Exception):
                await hm.edit("Sorry! API is dead or maybe your link is broken.")
            return

    if not data:
        with suppress(Exception):
            await hm.edit("Sorry! API is dead or maybe your link is broken.")
        return

    if isinstance(data, dict) and (data.get("error_type") == "MULTIPLE_FILES" or data.get("is_folder")):
        msg = data.get("error_message") or "This link contains multiple files or a folder. Please provide a link with a single file."
        with suppress(Exception):
            await hm.edit(f"⚠️ **Multiple Files / Folder Not Allowed**\n\n{msg}")
        return

    effective_user_id = user_id or (m.sender_id if hasattr(m, "sender_id") else None)
    if effective_user_id:
        db.set(effective_user_id, time.monotonic(), ex=60)

    if int(data.get("sizebytes", 0)) > 524288000 and effective_user_id not in ADMINS:
        with suppress(Exception):
            await hm.edit(
                f"Sorry! File is too big.\n**I can download only 500MB and this file is of {data.get('size', 'N/A')}.**\nRather you can download this file from the link below:\n{url}",
                parse_mode="markdown",
            )
        return

    if int(data.get("sizebytes", 0)) > 10737418240 and effective_user_id in ADMINS:
        with suppress(Exception):
            await hm.edit(
                f"❌ **File Too Large**\n\nEven for admins, the limit is capped at **10.00 GB** to prevent VPS storage overload. This file is **{data['size']}**.",
                parse_mode="markdown"
            )
        return

    sender = VideoSender(
        client=client,
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


def register_terabox_bot(client):
    """Registers TeraBox Downloader Bot handlers onto client."""
    register_common_handlers(client, "TeraBox Downloader", WELCOME_TEXT)

    # ------------------ SETTINGS COMMAND (ADMINS ONLY) ------------------
    @client.on(events.NewMessage(pattern=r"^/settings$", incoming=True, outgoing=False, func=lambda x: x.is_private))
    async def settings_cmd(m: Message):
        if m.sender_id not in ADMINS:
            return await m.reply("⚠️ **Permission Denied**: This command is restricted to Bot Administrators.")
        
        token_status = "✅ ACTIVE" if is_token_system_enabled() else "❌ OFF (Direct Mode)"
        force_status = "✅ ACTIVE" if is_force_sub_enabled() else "❌ OFF"
        
        text = (
            "⚙️ **TeraBox Bot Settings Panel**\n\n"
            f"• **Shortlink Ads System:** `{token_status}`\n"
            f"• **Force Subscription (Channels):** `{force_status}`\n\n"
            "Select an option below to toggle live settings:"
        )
        
        btn_token_text = "Turn OFF Ads System" if is_token_system_enabled() else "Turn ON Ads System"
        btn_force_text = "Turn OFF Force Sub" if is_force_sub_enabled() else "Turn ON Force Sub"
        
        buttons = [
            [Button.inline(btn_token_text, data="toggle_token")],
            [Button.inline(btn_force_text, data="toggle_forcesub")],
            [Button.inline("✖️ Close Panel", data="close_settings")]
        ]
        await m.reply(text, buttons=buttons, parse_mode="markdown")

    @client.on(events.CallbackQuery(pattern=r"(toggle_token|toggle_forcesub|close_settings)"))
    async def settings_callback(event):
        if event.sender_id not in ADMINS:
            return await event.answer("⚠️ Admin only!", alert=True)
            
        data = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data
        
        if data == "close_settings":
            await event.delete()
            return
            
        if data == "toggle_token":
            current = is_token_system_enabled()
            db.set("cfg_use_token_system", str(not current))
            await event.answer("Toggled Ads System!", alert=False)
            
        elif data == "toggle_forcesub":
            current = is_force_sub_enabled()
            db.set("cfg_use_force_sub", str(not current))
            await event.answer("Toggled Force Sub!", alert=False)
            
        token_status = "✅ ACTIVE" if is_token_system_enabled() else "❌ OFF (Direct Mode)"
        force_status = "✅ ACTIVE" if is_force_sub_enabled() else "❌ OFF"
        btn_token_text = "Turn OFF Ads System" if is_token_system_enabled() else "Turn ON Ads System"
        btn_force_text = "Turn OFF Force Sub" if is_force_sub_enabled() else "Turn ON Force Sub"
        
        new_text = (
            "⚙️ **TeraBox Bot Settings Panel**\n\n"
            f"• **Shortlink Ads System:** `{token_status}`\n"
            f"• **Force Subscription (Channels):** `{force_status}`\n\n"
            "Select an option below to toggle live settings:"
        )
        buttons = [
            [Button.inline(btn_token_text, data="toggle_token")],
            [Button.inline(btn_force_text, data="toggle_forcesub")],
            [Button.inline("✖️ Close Panel", data="close_settings")]
        ]
        await event.edit(new_text, buttons=buttons, parse_mode="markdown")

    # ------------------ ADMIN CUSTOM THUMBNAIL HANDLERS ------------------
    @client.on(events.NewMessage(pattern=r"^/(setthumb|set_thumb)", incoming=True, outgoing=False, func=lambda x: x.is_private))
    async def set_custom_thumbnail(m: Message):
        if m.sender_id not in ADMINS:
            return await m.reply("⚠️ **Permission Denied**: Only bot admins can set a custom thumbnail.")

        reply_msg = await m.get_reply_message()
        target_msg = reply_msg if reply_msg and reply_msg.photo else (m if m.photo else None)

        if not target_msg:
            return await m.reply(
                "🖼️ **How to set Custom Thumbnail:**\n\n"
                "1. Send a photo with caption `/setthumb`\n"
                "**OR**\n"
                "2. Reply to any photo with `/setthumb`"
            )

        hm = await m.reply("⏳ **Saving custom thumbnail...**")
        try:
            admin_thumb_path = os.path.join(os.getcwd(), "admin_thumb.jpg")
            await m.client.download_media(target_msg.photo, file=admin_thumb_path)
            await hm.edit("✅ **Custom Thumbnail Saved Successfully!**\nAll future downloads will use this thumbnail.")
        except Exception as e:
            await hm.edit(f"❌ **Failed to save thumbnail**: `{e}`")

    @client.on(events.NewMessage(pattern=r"^/(delthumb|removethumb)", incoming=True, outgoing=False, func=lambda x: x.is_private))
    async def delete_custom_thumbnail(m: Message):
        if m.sender_id not in ADMINS:
            return await m.reply("⚠️ Only bot admins can delete custom thumbnails.")
        admin_thumb_path = os.path.join(os.getcwd(), "admin_thumb.jpg")
        if os.path.exists(admin_thumb_path):
            os.remove(admin_thumb_path)
            await m.reply("✅ **Custom Thumbnail Deleted.**")
        else:
            await m.reply("ℹ️ No custom thumbnail currently set.")

    @client.on(events.NewMessage(pattern=r"^/clean$"))
    async def clean_videos(m: Message):
        if m.sender_id not in ADMINS:
            return
        remove_all_videos()
        await m.reply("Removed all videos from cache.")

    # ------------------ RAW JOIN REQUEST HANDLER ------------------
    @client.on(events.Raw(types.UpdateBotChatInviteRequester))
    async def handle_raw_join_request(event):
        try:
            user_id = event.user_id
            chat_id = event.peer.channel_id if hasattr(event.peer, 'channel_id') else event.peer.chat_id
            chat_id = int(f"-100{chat_id}")
            from pymongo import MongoClient
            client_mongo = MongoClient(MONGODB_URI)
            db_mongo = client_mongo['terabox_downloader']
            db_mongo['joinrequests'].update_one(
                {"userId": user_id, "chatId": chat_id},
                {"$set": {"status": "pending", "createdAt": datetime.utcnow()}},
                upsert=True
            )
        except Exception:
            pass

    # ------------------ TERABOX LINK RECEIVER ------------------
    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: m.is_private and m.text and get_urls_from_string(m.text)))
    async def get_message(m: Message):
        global is_processing, download_queue
        url = get_urls_from_string(m.text)
        if not url:
            return await m.reply("Please enter a valid url.")
            
        allowed = await verify_user_access(client, m, "TeraBox")
        if not allowed:
            return

        from modules.common import StorageGuard
        if not StorageGuard.is_safe_to_download():
            return await m.reply("⚠️ **Server Storage Busy**\n\nAuto-cleaner is freeing up disk space. Please retry in 1 minute.")

        is_spam = db.get(m.sender_id)
        if is_spam and m.sender_id not in ADMINS:
            ttl = db.ttl(m.sender_id)
            t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
            return await m.reply(f"You are spamming.\n**Please wait {t.to_humanreadable()} and try again.**", parse_mode="markdown")

        hm = await m.reply("Fetching link details...")
        try:
            data = get_data(url)
        except Exception:
            return await hm.edit("Sorry! API is dead or maybe your link is broken.")

        if not data:
            return await hm.edit("Sorry! API is dead or maybe your link is broken.")

        if isinstance(data, dict) and (data.get("error_type") == "MULTIPLE_FILES" or data.get("is_folder")):
            msg = data.get("error_message") or "This link contains multiple files or a folder. Please provide a link with a single file."
            return await hm.edit(f"⚠️ **Multiple Files / Folder Not Allowed**\n\n{msg}")

        shorturl = extract_code_from_url(url)
        if not shorturl:
            from uuid import uuid4
            shorturl = str(uuid4())[:10]

        db.set(f"req_url_{shorturl}", url, ex=86400)
        db.set(f"req_data_{shorturl}", json.dumps(data), ex=86400)

        file_name = data.get("file_name", "Unknown File")
        file_size = data.get("size", "N/A")

        queue_notice = ""
        if is_processing or len(download_queue) > 0:
            total_waiting = len(download_queue) + (1 if is_processing else 0)
            queue_notice = f"\n\n⏳ **Queue Status:** `{total_waiting}` download(s) active/queued."

        text = f"""
📥 **File Details Found!**

📁 **Name**: `{file_name}`
📦 **Size**: `{file_size}`{queue_notice}

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

    # ------------------ FORMAT CALLBACK ------------------
    @client.on(events.CallbackQuery(pattern=r"^dl_(v|d)_(.+)"))
    async def download_format_callback(event):
        global is_processing, download_queue, cached_loading_media
        match = event.pattern_match
        fmt = match.group(1).decode("utf-8") if isinstance(match.group(1), bytes) else match.group(1)
        shorturl = match.group(2).decode("utf-8") if isinstance(match.group(2), bytes) else match.group(2)
        as_doc = (fmt == "d")
        user_id = event.sender_id

        raw_url = db.get(f"req_url_{shorturl}")
        url = (raw_url.decode("utf-8") if isinstance(raw_url, bytes) else str(raw_url)) if raw_url else f"https://1024terabox.com/s/{shorturl}"

        data = None
        raw_data = db.get(f"req_data_{shorturl}")
        if raw_data:
            with suppress(Exception):
                data = json.loads(raw_data.decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data))

        hm = await event.get_message()
        fmt_name = "Document" if as_doc else "Video"
        fname = data.get("file_name", "File") if data else "File"

        with suppress(Exception):
            await hm.edit(
                f"🌀 **Preparing Download...**\n\n"
                f"📁 **File:** `{fname}`\n"
                f"⚡ **Format:** `{fmt_name}`\n"
                f"⏳ **Status:** `Connecting to server...`",
                buttons=None
            )

        loading_msg = None
        if not cached_loading_media:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for filename in ["loading.gif", "loading.mp4", "loading.webp", "loading.jpg"]:
                p = os.path.join(base_dir, filename)
                if os.path.exists(p):
                    cached_loading_media = p
                    break
        if cached_loading_media:
            with suppress(Exception):
                loading_msg = await event.respond(file=cached_loading_media)

        # Check fast-forward cache
        code = extract_code_from_url(url) or shorturl
        if code:
            fileid = db.get_key(code)
            if fileid:
                if loading_msg:
                    with suppress(Exception):
                        await loading_msg.delete()
                first_id = fileid.split(",")[0] if (isinstance(fileid, str) and "," in fileid) else fileid
                uid = db.get_key(f"mid_{fileid}") or db.get_key(f"mid_{first_id}") or code
                check = await VideoSender.forward_file(
                    file_id=fileid, message=hm, client=client, edit_message=hm, uid=uid, as_doc=as_doc
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
            "loading_msg": loading_msg,
        }

        if is_processing:
            download_queue.append(task_payload)
            position = len(download_queue)
            with suppress(Exception):
                await hm.edit(
                    f"⏳ **Added to Download Queue!**\n\n"
                    f"📁 **File:** `{fname}` ({fmt_name})\n"
                    f"🔢 **Your Position in Queue:** `#{position}`\n\n"
                    f"Please keep this chat open. Your file will automatically be delivered here!"
                )
        else:
            is_processing = True
            asyncio.create_task(run_task(client, task_payload))
