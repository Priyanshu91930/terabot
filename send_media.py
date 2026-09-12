import asyncio
import logging
import os
import time
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)

import telethon
from telethon import Button, TelegramClient, events, utils
from telethon.events.newmessage import NewMessage
from telethon.tl.functions.channels import GetMessagesRequest
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.patched import Message
from telethon.tl.types import Document
from telethon.types import UpdateEditMessage

from cansend import CanSend
from config import BOT_USERNAME, PRIVATE_CHAT_ID
from FastTelethon import upload_file  # unused, kept for compatibility
from redis_db import db
from tools import (
    convert_seconds,
    download_file,
    download_image_to_bytesio,
    extract_code_from_url,
    get_formatted_size,
)


def split_file(file_path, max_size_bytes=2000000000):
    import os
    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]
    
    parts = []
    part_num = 1
    file_dir = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    base_name, ext = os.path.splitext(file_name)
    
    buffer_size = 50 * 1024 * 1024 # 50 MB buffer
    
    with open(file_path, "rb") as f:
        while True:
            part_name = os.path.join(file_dir, f"{base_name}.part{part_num}{ext}")
            bytes_written = 0
            
            with open(part_name, "wb") as part_file:
                while bytes_written < max_size_bytes:
                    to_read = min(buffer_size, max_size_bytes - bytes_written)
                    chunk = f.read(to_read)
                    if not chunk:
                        break
                    part_file.write(chunk)
                    bytes_written += len(chunk)
            
            if bytes_written == 0:
                try:
                    os.unlink(part_name)
                except:
                    pass
                break
                
            parts.append(part_name)
            part_num += 1
            
    return parts


class VideoSender:

    def __init__(
        self,
        client: TelegramClient,
        message: NewMessage.Event,
        edit_message: Message,
        url: str,
        data,
        as_doc: bool = False,
        user_id: int = None,
    ):
        self.client = client
        self.data = data
        self.url = url
        self.edit_message = edit_message
        self.message = message
        self.as_doc = as_doc
        self.user_id = user_id or (message.sender_id if hasattr(message, "sender_id") else None)
        self.uuid = str(uuid4())
        self.stop_sending = False
        self.thumbnail = self.get_thumbnail()
        self.can_send = CanSend()
        self.start_time = time.time()
        self.task = None
        self.client.add_event_handler(
            self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
        )
        self.caption = f"""
File Name: `{self.data['file_name']}`
Size: **{self.data["size"]}**

@TeraboxDownloaderINDIA
            """
        self.caption2 = f"""
Downloading `{self.data['file_name']}`
Size: **{self.data["size"]}**

@TeraboxDownloaderINDIA
            """

    async def progress_bar(self, current_downloaded, total_downloaded, state="Sending"):
        if not self.can_send.can_send():
            return

        bar_length = 15
        elapsed_time = time.time() - self.start_time
        upload_speed = current_downloaded / elapsed_time if elapsed_time > 0 else 0
        speed_line = f"⚡️ **Speed**: `{get_formatted_size(upload_speed)}/s`"

        state_emoji = "📥" if "download" in state.lower() else "📤"

        if total_downloaded > 0:
            percent = current_downloaded / total_downloaded
            filled_len = int(percent * bar_length)
            bar = "■" * filled_len + "□" * (bar_length - filled_len)
            progress_line = f"📊 **Progress**: `[{bar}] {percent:.2%}`"
            size_line = f"📦 **Loaded**: `{get_formatted_size(current_downloaded)}` of `{get_formatted_size(total_downloaded)}`"
            time_remaining = (total_downloaded - current_downloaded) / upload_speed if upload_speed > 0 else 0
            time_line = f"⏳ **Time Left**: `{convert_seconds(time_remaining)}`"
        else:
            bar = "□" * bar_length
            progress_line = f"📊 **Progress**: `[{bar}]`"
            size_line = f"📦 **Loaded**: `{get_formatted_size(current_downloaded)}` of `Unknown`"
            time_line = "⏳ **Time Left**: `Calculating...`"

        text = f"""
{state_emoji} **{state} Video...**

📁 **File**: `{self.data['file_name']}`
{size_line}

{progress_line}
{speed_line}
{time_line}

__Powered by @TeraboxDownloaderINDIA__
"""

        await self.edit_message.edit(
            text,
            parse_mode="markdown",
            buttons=[Button.inline("Stop ⛔", data=f"stop{self.uuid}")],
        )

    async def send_media(self, shorturl):
        path = Path(self.data["file_name"])
        if not os.path.exists(path):
            direct_url = self.data.get("direct_link") or self.data.get("link")
            fallback_url = self.data.get("link") or self.data.get("direct_link")
            
            if not direct_url or not isinstance(direct_url, str) or not direct_url.startswith(("http://", "https://")):
                log.error(f"Invalid download link received: {direct_url}")
                return await self.handle_failed_download()

            download = None
            try:
                download_task = asyncio.create_task(
                    download_file(
                        direct_url,
                        self.data["file_name"],
                        self.progress_bar,
                        headers=self.data.get("headers"),
                    )
                )
                download = await asyncio.gather(download_task)
            except Exception as e:
                log.warning(f"Primary download attempt failed: {e}")
                if fallback_url and fallback_url != direct_url and fallback_url.startswith(("http://", "https://")):
                    await self.edit_message.edit("Failed to Download the media. trying again...")
                    try:
                        download_task = asyncio.create_task(
                                download_file(
                                    fallback_url,
                                    self.data["file_name"],
                                    self.progress_bar,
                                    headers=self.data.get("headers"),
                                )
                            )
                        download = await asyncio.gather(download_task)
                    except Exception as ex:
                        log.error(f"Fallback download attempt failed: {ex}")
                        return await self.handle_failed_download()
                else:
                    return await self.handle_failed_download()
        else:
            download = [path]
        if not download or not download[0] or not os.path.exists(download[0]):
            return await self.handle_failed_download()
        self.download = Path(download[0])
        file_size = os.path.getsize(self.download)
        max_size = 2000000000 # 2GB
        
        files_to_save = []
        try:
            if file_size > max_size:
                await self.edit_message.edit(f"📦 Large file detected ({get_formatted_size(file_size)}).\nSplitting into parts for Telegram Bot 2GB limit...")
                parts = split_file(self.download, max_size)
                
                sent_files = []
                for i, part in enumerate(parts):
                    part_name = os.path.basename(part)
                    await self.edit_message.edit(f"📤 Uploading part {i+1} of {len(parts)}: `{part_name}`...")
                    
                    self.start_time = time.time()
                    if not self.as_doc:
                        attributes, mime_type = utils.get_attributes(part, supports_streaming=True)
                        from telethon.tl.types import DocumentAttributeVideo
                        has_video_attr = any(isinstance(a, DocumentAttributeVideo) for a in (attributes or []))
                        if not has_video_attr:
                            if attributes is None:
                                attributes = []
                            attributes.append(DocumentAttributeVideo(duration=0, w=0, h=0, supports_streaming=True))
                    else:
                        attributes = None
                        mime_type = None

                    part_caption = f"{self.caption}\n\n📂 **Part {i+1} of {len(parts)}**"
                    
                    if self.thumbnail and hasattr(self.thumbnail, 'seek'):
                        self.thumbnail.seek(0)

                    file = await asyncio.wait_for(
                        self.client.send_file(
                            self.message.chat.id,
                            file=part,
                            caption=part_caption,
                            reply_to=self.message.id,
                            force_document=self.as_doc,
                            attributes=attributes if not self.as_doc else None,
                            supports_streaming=not self.as_doc,
                            thumb=self.thumbnail,
                            parse_mode="markdown",
                            mime_type=mime_type,
                            progress_callback=self.progress_bar,
                            buttons=[
                                [
                                    Button.url("Channel 📢", url="https://t.me/TeraboxDownloaderINDIA"),
                                    Button.url("Group 💬", url="https://t.me/+L7tcuoCsTaMxZWVl"),
                                ],
                            ],
                        ),
                        timeout=3600,
                    )
                    sent_files.append(file)
                    try:
                        os.unlink(part)
                    except:
                        pass
                        
                # Clean up original file
                try:
                    os.unlink(self.download)
                except:
                    pass
                try:
                    os.unlink(self.data["file_name"])
                except:
                    pass
                    
                self.client.remove_event_handler(
                    self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
                )
                try:
                    await self.edit_message.delete()
                except:
                    pass
                files_to_save = sent_files
            else:
                log.info(f"[UPLOAD] Starting upload for: {self.data['file_name']} ({os.path.getsize(self.download)} bytes)")
                await self.edit_message.edit(
                    f"📤 **Uploading...**\n\n📁 `{self.data['file_name']}`\n📦 `{get_formatted_size(os.path.getsize(self.download))}`\n\n__Powered by @TeraboxDownloaderINDIA__",
                    parse_mode="markdown",
                )
                if not self.as_doc:
                    attributes, mime_type = utils.get_attributes(self.download, supports_streaming=True)
                    from telethon.tl.types import DocumentAttributeVideo
                    has_video_attr = any(isinstance(a, DocumentAttributeVideo) for a in (attributes or []))
                    if not has_video_attr:
                        if attributes is None:
                            attributes = []
                        attributes.append(DocumentAttributeVideo(duration=0, w=0, h=0, supports_streaming=True))
                else:
                    attributes = None
                    mime_type = None

                if self.thumbnail and hasattr(self.thumbnail, 'seek'):
                    self.thumbnail.seek(0)

                with open(self.download, "rb") as f:
                    file = await asyncio.wait_for(
                        self.client.send_file(
                            self.message.chat.id,
                            file=f,
                            caption=self.caption,
                            force_document=self.as_doc,
                            attributes=attributes if not self.as_doc else None,
                            supports_streaming=not self.as_doc,
                            thumb=self.thumbnail,
                            reply_to=self.message.id,
                            parse_mode="markdown",
                            mime_type=mime_type,
                            progress_callback=self.progress_bar,
                            buttons=[
                                [
                                    Button.url(
                                        "Direct Link",
                                        url=f"https://{BOT_USERNAME}.t.me?start={self.uuid}",
                                    ),
                                ],
                                [
                                    Button.url("Channel 📢", url="https://t.me/TeraboxDownloaderINDIA"),
                                    Button.url("Group 💬", url="https://t.me/+L7tcuoCsTaMxZWVl"),
                                ],
                            ],
                        ),
                        timeout=3600,
                    )
                try:
                    os.unlink(self.download)
                except Exception:
                    pass
                try:
                    os.unlink(self.data["file_name"])
                except Exception:
                    pass
                log.info(f"[UPLOAD] send_file SUCCESS! File delivered to user.")
                files_to_save = [file]
        except asyncio.TimeoutError:
            log.error(f"[UPLOAD] send_file TIMEOUT after 3600s for: {self.data['file_name']}")
            self.client.remove_event_handler(
                self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
            )
            try:
                os.unlink(self.download)
            except Exception:
                pass
            try:
                await self.edit_message.edit(
                    "❌ **Telegram Timeout**\n\nFile data was uploaded but Telegram took too long to confirm. Please try again.",
                    parse_mode="markdown",
                )
            except Exception:
                pass
        except Exception as e:
            self.client.remove_event_handler(
                self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
            )
            try:
                os.unlink(self.download)
            except Exception:
                pass
            try:
                os.unlink(self.data["file_name"])
            except Exception:
                pass
            return await self.handle_failed_download()

        if files_to_save:
            await self.save_forward_file(files_to_save, shorturl)

    async def handle_failed_download(self):
        try:
            os.unlink(self.data["file_name"])
        except Exception:
            pass
        try:
            os.unlink(self.download)
        except Exception:
            pass
        try:
            await self.edit_message.edit(
                f"Sorry! Download Failed but you can download it from [here]({self.data['direct_link']}) or [here]({self.data['link']}).",
                parse_mode="markdown",
                buttons=[Button.url("Download", data=self.data["direct_link"])],
            )
        except Exception:
            pass

    async def save_forward_file(self, files, shorturl):
        if not isinstance(files, list):
            files = [files]

        forwarded_messages = await self.client.forward_messages(
            PRIVATE_CHAT_ID,
            files,
            from_peer=self.message.chat.id,
            with_my_score=True,
            background=True,
        )

        msg_ids = [m.id for m in forwarded_messages if m and hasattr(m, "id")]
        if msg_ids:
            if len(msg_ids) == 1:
                val = str(msg_ids[0])
            else:
                val = ",".join(str(i) for i in msg_ids)

            db.set_key(self.uuid, val)
            db.set_key(f"mid_{val}", self.uuid)
            db.set_key(f"mid_{msg_ids[0]}", self.uuid)
            if shorturl:
                db.set_key(shorturl, val)

        self.client.remove_event_handler(
            self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
        )
        try:
            await self.edit_message.delete()
        except Exception:
            pass
        try:
            os.unlink(self.data["file_name"])
        except Exception:
            pass
        try:
            os.unlink(self.download)
        except Exception:
            pass
        if self.user_id:
            db.set(self.user_id, time.monotonic(), ex=60)

    async def send_video(self):
        self.thumbnail = self.get_thumbnail()
        shorturl = extract_code_from_url(self.url)
        if not shorturl:
            return await self.edit_message.edit("Seems like your link is invalid.")

        try:
            if self.edit_message:
                await self.edit_message.delete()
        except Exception as e:
            pass

        if self.user_id:
            db.set(self.user_id, time.monotonic(), ex=60)

        if self.thumbnail and hasattr(self.thumbnail, "seek"):
            self.thumbnail.seek(0)

        self.edit_message = await self.message.reply(
            self.caption2, file=self.thumbnail, parse_mode="markdown"
        )
        self.task = asyncio.create_task(self.send_media(shorturl))

    async def stop(self, event):
        self.task.cancel()
        self.client.remove_event_handler(
            self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
        )
        await event.answer("Process stopped.")
        try:
            os.unlink(self.data["file_name"])
        except Exception:
            pass
        try:
            os.unlink(self.download)
        except Exception:
            pass
        try:
            await self.edit_message.delete()
        except Exception:
            pass

    def get_thumbnail(self):
        from io import BytesIO
        admin_thumb_path = os.path.join(os.getcwd(), "admin_thumb.jpg")
        if os.path.exists(admin_thumb_path):
            try:
                with open(admin_thumb_path, "rb") as f:
                    content = BytesIO(f.read())
                    content.name = "thumbnail.jpg"
                    return content
            except Exception as e:
                log.error(f"Error reading admin custom thumbnail: {e}")

        thumb_url = self.data.get("thumb") if isinstance(self.data, dict) else None
        if thumb_url:
            return download_image_to_bytesio(thumb_url, "thumbnail.png")
        return None

    @staticmethod
    async def forward_file(
        client: TelegramClient,
        file_id: int | str,
        message: Message,
        edit_message: UpdateEditMessage = None,
        uid: str = None,
        as_doc: bool = False,
    ):
        if edit_message:
            try:
                await edit_message.delete()
            except Exception:
                pass

        if isinstance(file_id, (list, tuple)):
            ids = [int(i) for i in file_id]
        elif isinstance(file_id, str) and "," in file_id:
            ids = [int(i.strip()) for i in file_id.split(",") if i.strip()]
        else:
            try:
                ids = [int(file_id)]
            except Exception:
                return False

        try:
            result = await client(
                GetMessagesRequest(channel=PRIVATE_CHAT_ID, id=ids)
            )
        except Exception as e:
            log.error(f"GetMessagesRequest failed: {e}")
            return False

        if not result or not result.messages:
            return False

        msg_map = {m.id: m for m in result.messages if m and hasattr(m, "id") and hasattr(m, "media") and m.media}
        ordered_messages = [msg_map[i] for i in ids if i in msg_map]

        if not ordered_messages:
            return False

        sender_id = message.sender_id if hasattr(message, "sender_id") else None

        success_count = 0
        for idx, msg in enumerate(ordered_messages):
            media = msg.media.document if hasattr(msg.media, "document") and msg.media.document else msg.media
            caption = msg.message or ""

            try:
                await message.reply(
                    message=caption,
                    file=media,
                    background=True,
                    reply_to=message.id if hasattr(message, "id") else None,
                    force_document=as_doc,
                    buttons=[
                        [
                            Button.url(
                                "Direct Link",
                                url=f"https://{BOT_USERNAME}.t.me?start={uid or ''}",
                            ),
                        ],
                        [
                            Button.url("Channel 📢", url="https://t.me/TeraboxDownloaderINDIA"),
                            Button.url("Group 💬", url="https://t.me/+L7tcuoCsTaMxZWVl"),
                        ],
                    ],
                    parse_mode="markdown",
                )
                success_count += 1
            except Exception as e:
                log.error(f"Error forwarding batch message part {idx+1}: {e}")

        if success_count > 0:
            if sender_id:
                db.set(sender_id, time.monotonic(), ex=60)
                db.incr(f"check_{sender_id}", 1)
            return True
        return False

