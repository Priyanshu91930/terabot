import os
import time
import shutil
import logging
import asyncio
from datetime import datetime
import humanreadable as hr
from telethon import Button, events
from telethon.tl.custom.message import Message

from config import (ADMINS, FORCE_SUB_ID_1, FORCE_SUB_ID_2, FORCE_SUB_ID_3,
                    FORCE_LINK_1, FORCE_LINK_2, FORCE_LINK_3,
                    UPDATE_CHANNEL_URL, MONGODB_URI, USE_TOKEN_SYSTEM,
                    MIN_SHORTLINK_TIME, BOT_USERNAME)
from redis_db import db
from pymongo import MongoClient
from tools import is_user_on_chat, generate_shortenedUrl

log = logging.getLogger(__name__)

# Global semaphore: Allows at most 2 concurrent file downloads across all bots simultaneously
# Guarantees VPS disk usage NEVER exceeds ~1.2 GB at peak (out of 30 GB)!
GLOBAL_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)


# ==================== VPS STORAGE GUARD ====================
class StorageGuard:
    MIN_FREE_GB = 2.5  # If free disk is < 2.5 GB, triggers emergency cleanup

    @classmethod
    def get_free_space_gb(cls) -> float:
        try:
            total, used, free = shutil.disk_usage(os.getcwd())
            return round(free / (1024 ** 3), 2)
        except Exception:
            return 20.0

    @classmethod
    def get_total_space_gb(cls) -> float:
        try:
            total, used, free = shutil.disk_usage(os.getcwd())
            return round(total / (1024 ** 3), 2)
        except Exception:
            return 30.0

    @classmethod
    def clean_orphaned_files(cls, max_age_seconds: int = 600):
        """Removes leftover temporary files older than max_age_seconds (10 minutes)."""
        now = time.time()
        cleaned_count = 0
        cleaned_bytes = 0
        
        folders_to_check = [
            os.path.join(os.getcwd(), "downloads"),
            os.getcwd(),
        ]
        
        for folder in folders_to_check:
            if not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                for f in files:
                    if f.endswith(('.mp4', '.mkv', '.webm', '.part', '.jpg', '.png', '.webp', '.zip')):
                        # Protect system files and thumbnails
                        if f in ["admin_thumb.jpg"]:
                            continue
                        fpath = os.path.join(root, f)
                        try:
                            mtime = os.path.getmtime(fpath)
                            if (now - mtime) > max_age_seconds:
                                sz = os.path.getsize(fpath)
                                os.remove(fpath)
                                cleaned_count += 1
                                cleaned_bytes += sz
                        except Exception:
                            pass
        if cleaned_count > 0:
            mb = cleaned_bytes / (1024 * 1024)
            log.info(f"[StorageGuard] Cleaned {cleaned_count} leftover files ({mb:.2f} MB freed).")

    @classmethod
    def is_safe_to_download(cls) -> bool:
        free_gb = cls.get_free_space_gb()
        if free_gb < cls.MIN_FREE_GB:
            cls.clean_orphaned_files(max_age_seconds=60)
            free_gb = cls.get_free_space_gb()
            return free_gb >= 1.5
        return True


async def auto_cleaner_task():
    """Background janitor that sweeps and purges stale temp files every 10 minutes."""
    while True:
        try:
            await asyncio.sleep(600)
            StorageGuard.clean_orphaned_files(max_age_seconds=600)
        except Exception as e:
            log.error(f"[AutoCleaner] Error: {e}")


mongo_client = MongoClient(MONGODB_URI)
mongo_db = mongo_client['terabox_downloader']
bot_users_col = mongo_db['botusers']


def is_token_system_enabled() -> bool:
    val = db.get("cfg_use_token_system")
    if val is not None:
        return val.decode("utf-8") == "True"
    return USE_TOKEN_SYSTEM


def is_force_sub_enabled() -> bool:
    val = db.get("cfg_use_force_sub")
    if val is not None:
        return val.decode("utf-8") == "True"
    return True


def _sync_save_bot_user(user_id, first_name, username, bot_type="generic"):
    try:
        bot_users_col.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'user_id': user_id,
                    'first_name': first_name,
                    'username': username,
                    'last_bot': bot_type,
                    'updated_at': datetime.utcnow()
                },
                '$setOnInsert': {
                    'created_at': datetime.utcnow()
                }
            },
            upsert=True
        )
    except Exception as e:
        log.error(f"[DB] Error saving bot user: {e}")


async def save_bot_user_async(event, bot_type="generic"):
    try:
        sender = await event.get_sender()
        user_id = event.sender_id or (getattr(sender, 'id', None) if sender else None)
        if not user_id:
            return
        first_name = getattr(sender, 'first_name', '') or '' if sender else ''
        username = getattr(sender, 'username', '') or '' if sender else ''
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _sync_save_bot_user, user_id, first_name, username, bot_type)
    except Exception:
        pass


async def check_user_force_sub(client, user_id: int):
    if user_id in ADMINS or not is_force_sub_enabled():
        return True, []
    
    from config import FORCE_SUB_CHANNELS
    channels_to_join = []
    
    for ch in FORCE_SUB_CHANNELS:
        ch_id = ch.get("id")
        ch_link = ch.get("link")
        if not ch_id and not ch_link:
            continue
        joined = await is_user_on_chat(client, ch_id, user_id, chat_link=ch_link)
        if not joined:
            channels_to_join.append(ch)

    if not channels_to_join:
        return True, []

    bot_uname = getattr(client, "bot_username", BOT_USERNAME)
    buttons = []
    row = []
    for ch in channels_to_join:
        row.append(Button.url(ch.get("name", "Join Channel 📢"), url=ch.get("link", "")))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([Button.url("ReCheck ♻️", url=f"https://t.me/{bot_uname}?start=true")])
    return False, buttons


async def verify_user_access(client, event, service_name: str = "Media"):
    """
    Checks both Force Subscription and Monetization Token.
    Returns True if user is allowed to download.
    If not, automatically replies with the required action and returns False.
    """
    user_id = event.sender_id
    if user_id in ADMINS:
        return True

    # 1. Force Sub check
    is_joined, sub_buttons = await check_user_force_sub(client, user_id)
    if not is_joined:
        await event.reply(
            "❌ **Force Join Active**\n\n"
            "You must join all our channels and group to download! "
            "Please join them all and then send your link again.",
            buttons=sub_buttons
        )
        return False

    # 2. Token / Ads system check
    if is_token_system_enabled():
        is_user_active = db.get(f"active_{user_id}")
        if not is_user_active:
            bot_uname = getattr(client, "bot_username", BOT_USERNAME)
            shortened_url = generate_shortenedUrl(user_id, bot_uname)
            if not shortened_url:
                shortened_url = f"https://t.me/{bot_uname}?start=true"
            
            sender = await event.get_sender()
            fname = (getattr(sender, 'first_name', '') or getattr(sender, 'username', 'User')) if sender else 'User'
            ad_text = (
                f"👋 **Hey {fname}!**\n\n"
                f"Your Ads Token has expired. Please verify a quick ad to use the {service_name} Bot for the next **1 hour**.\n\n"
                "⏱ **Token Timeout:** 1 Hour\n"
                "🔓 After 1 quick shortlink, you get unlimited fast downloads!"
            )
            await event.reply(
                ad_text,
                buttons=[
                    [Button.url("Click Here To Get 1-Hour Access 🔓", url=shortened_url)],
                    [Button.url("How to Open Link ❓", url=UPDATE_CHANNEL_URL)],
                ],
                parse_mode="markdown"
            )
            return False

    return True


group_cooldowns = {}

def register_common_handlers(client, service_name: str, welcome_banner: str):
    """Registers standard handlers (debug, start, gen, settings, broadcast, stats, join requests) on client."""
    
    # Handle pending join requests and save in MongoDB
    from telethon.tl import types
    @client.on(events.Raw(types.UpdateBotChatInviteRequester))
    async def _raw_join_req(event):
        try:
            uid = event.user_id
            raw_cid = event.peer.channel_id if hasattr(event.peer, 'channel_id') else event.peer.chat_id
            full_cid = int(f"-100{raw_cid}")
            bot_users_col.database['joinrequests'].update_one(
                {"userId": uid, "chatId": full_cid},
                {"$set": {"status": "pending", "createdAt": datetime.utcnow()}},
                upsert=True
            )
        except Exception:
            pass

    # User activity & tracker
    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda x: x.is_private))
    async def _tracker(event):
        asyncio.create_task(save_bot_user_async(event, service_name))

    # /start handler
    @client.on(events.NewMessage(pattern=r"^/start(?: (.*))?$"))
    async def _start(m: Message):
        arg = m.pattern_match.group(1)
        bot_uname = getattr(client, "bot_username", BOT_USERNAME)
        
        # Token redemption: /start token_<uuid>
        if arg and arg.startswith("token_"):
            if not is_token_system_enabled():
                return await m.reply("The token system is currently disabled. You can download links directly!")
            
            uuid_val = arg.replace("token_", "").strip()
            token_data = db.get(f"token_{uuid_val}")
            if not token_data:
                return await m.reply("❌ **Invalid or expired token!**\nUse /gen to get a new token link.")
            
            token_str = token_data.decode("utf-8")
            parts = token_str.split("|")
            sender_id = parts[0]
            created_at = float(parts[2]) if len(parts) > 2 else 0.0
            
            if m.sender_id != int(sender_id):
                return await m.reply("❌ This token was generated for another user. Hit /gen to get your own.")
                
            if created_at > 0 and m.sender_id not in ADMINS:
                elapsed = time.time() - created_at
                if elapsed < MIN_SHORTLINK_TIME:
                    db.delete(f"token_{uuid_val}")
                    new_url = generate_shortenedUrl(m.sender_id, bot_uname)
                    return await m.reply(
                        "❌ **Bypass Detected!**\nPlease complete the ad properly.",
                        buttons=[Button.url("Click Here To Complete Ad", url=new_url or "")]
                    )
            
            db.set(f"active_{m.sender_id}", time.time(), ex=3600)
            db.delete(f"token_{uuid_val}")
            return await m.reply("✅ **Ad verification successful!**\nYou now have unlimited access for **1 hour**! Send your link to download. 🚀")

        # Standard /start
        is_joined, buttons = await check_user_force_sub(client, m.sender_id)
        if not is_joined:
            return await m.reply(
                f"👋 **Welcome to {service_name} Bot!**\n\n"
                "Please join all our channels and group below to use this bot:",
                buttons=buttons
            )
        
        await m.reply(welcome_banner, parse_mode="markdown")

    # /gen command
    @client.on(events.NewMessage(pattern=r"^/gen$"))
    async def _gen(m: Message):
        if not is_token_system_enabled():
            return await m.reply("The token system is currently disabled. All downloads are free & direct!")
            
        is_user_active = db.get(f"active_{m.sender_id}")
        if is_user_active:
            ttl = db.ttl(f"active_{m.sender_id}")
            t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
            return await m.reply(f"You already have active access!\nExpires in: **{t.to_humanreadable()}**.")
            
        bot_uname = getattr(client, "bot_username", BOT_USERNAME)
        short_url = generate_shortenedUrl(m.sender_id, bot_uname)
        if not short_url:
            return await m.reply("Something went wrong while generating token. Please try again.")
            
        await m.reply(
            f"🔑 **1-Hour Access Token for {service_name}**\n\n"
            "Click the button below and pass the ad verification to activate your 1-hour session:",
            buttons=[
                [Button.url("Get 1-Hour Token 🔓", url=short_url)],
                [Button.url("Updates Channel 📢", url=UPDATE_CHANNEL_URL)]
            ],
            parse_mode="markdown"
        )

    # /stats command
    @client.on(events.NewMessage(pattern=r"^/stats$"))
    async def _stats(m: Message):
        if m.sender_id not in ADMINS:
            return
        total_users = bot_users_col.count_documents({})
        active_tokens = len(db.keys("active_*"))
        free_disk = StorageGuard.get_free_space_gb()
        total_disk = StorageGuard.get_total_space_gb()
        await m.reply(
            f"📊 **{service_name} Bot Stats**\n\n"
            f"👤 **Total Registered Users:** `{total_users}`\n"
            f"🔑 **Currently Active Sessions:** `{active_tokens}`\n"
            f"💾 **VPS Disk Free:** `{free_disk} GB / {total_disk} GB`\n"
            f"🤖 **Bot Username:** @{getattr(client, 'bot_username', 'Unknown')}"
        )

    # /broadcast command (ADMINS ONLY)
    @client.on(events.NewMessage(pattern=r"^/broadcast(?: (.*))?$"))
    async def _broadcast(m: Message):
        if m.sender_id not in ADMINS:
            return
        reply_msg = await m.get_reply_message()
        broadcast_text = m.pattern_match.group(1) or ""
        if not reply_msg and not broadcast_text.strip():
            return await m.reply("Usage: `/broadcast <message>` or reply to a message with `/broadcast`")
            
        users = list(bot_users_col.find({}, {"user_id": 1}))
        total_users = len(users)
        progress_msg = await m.reply(f"📢 **Starting Broadcast to {total_users} users from @{getattr(client, 'bot_username', 'bot')}...**")
        
        success = 0
        failed = 0
        blocked = 0
        for u in users:
            uid = u.get("user_id")
            if not uid:
                continue
            try:
                if reply_msg:
                    await client.send_message(uid, reply_msg)
                else:
                    await client.send_message(uid, broadcast_text.strip(), parse_mode="markdown")
                success += 1
            except Exception as err:
                err_str = str(err).lower()
                if "user is blocked" in err_str or "deactivated" in err_str:
                    blocked += 1
                    bot_users_col.delete_one({"user_id": uid})
                else:
                    failed += 1
            await asyncio.sleep(0.04) # Smooth rate limiting
            
        await progress_msg.edit(
            f"✅ **Broadcast Completed!**\n\n"
            f"🎯 Total: `{total_users}`\n"
            f"✅ Success: `{success}`\n"
            f"🚫 Blocked/Deleted: `{blocked}`\n"
            f"❌ Failed: `{failed}`"
        )

    # Group Auto-Reply
    @client.on(events.NewMessage(incoming=True, outgoing=False, func=lambda m: (m.is_group or m.is_channel) and m.text))
    async def _group_reply(m: Message):
        bot_uname = getattr(client, 'bot_username', BOT_USERNAME)
        text_lower = m.text.lower()
        if bot_uname.lower() in text_lower or service_name.lower().split()[0] in text_lower:
            now = time.time()
            if m.chat_id in group_cooldowns and (now - group_cooldowns[m.chat_id]) < 45:
                return
            group_cooldowns[m.chat_id] = now
            await m.reply(
                f"Hey there! 👋 I am the **{service_name} Bot**.\nClick below to open me in private and start downloading! 🚀",
                buttons=[[Button.url("Open in PM 🚀", url=f"https://t.me/{bot_uname}?start=true")]]
            )
