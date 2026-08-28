import asyncio
import os
import time
from pathlib import Path
from uuid import uuid4

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
from FastTelethon import upload_file
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
    ):
        self.client = client
        self.data = data
        self.url = url
        self.edit_message = edit_message
        self.message = message
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
            try:
                download_task = asyncio.create_task(
                    download_file(
                        self.data["direct_link"],
                        self.data["file_name"],
                        self.progress_bar,
                        headers=self.data.get("headers"),
                    )
                )
                download = await asyncio.gather(download_task)
            except:
                await self.edit_message.edit("Failed to Download the media. trying again.")
                try:
                    download_task = asyncio.create_task(
                            download_file(
                                self.data["link"],
                                self.data["file_name"],
                                self.progress_bar,
                                headers=self.data.get("headers"),
                            )
                        )
                    download = await asyncio.gather(download_task)
                except:
                    return await self.handle_failed_download()
        else:
            download = [path]
        if not download or not download[0] or not os.path.exists(download[0]):
            return await self.handle_failed_download()
        self.download = Path(download[0])
        file_size = os.path.getsize(self.download)
        max_size = 2000000000 # 2GB
        
        try:
            if file_size > max_size:
                await self.edit_message.edit(f"📦 Large file detected ({get_formatted_size(file_size)}).\nSplitting into parts for Telegram Bot 2GB limit...")
                parts = split_file(self.download, max_size)
                
                sent_files = []
                for i, part in enumerate(parts):
                    part_name = os.path.basename(part)
                    await self.edit_message.edit(f"📤 Uploading part {i+1} of {len(parts)}: `{part_name}`...")
                    
                    # Temporarily set start time for the part progress bar
                    self.start_time = time.time()
                    with open(part, "rb") as out:
                        res = await upload_file(
                            self.client, out, self.progress_bar, part_name
                        )
                        attributes, mime_type = utils.get_attributes(part)
                        part_caption = f"{self.caption}\n\n📂 **Part {i+1} of {len(parts)}**"
                        
                        file = await asyncio.wait_for(
                            self.client.send_file(
                                self.message.chat.id,
                                file=res,
                                caption=part_caption,
                                background=True,
                                reply_to=self.message.id,
                                allow_cache=True,
                                force_document=True,
                                parse_mode="markdown",
                                thumb=self.thumbnail,
                                mime_type=mime_type,
                                buttons=[
                                    [
                                        Button.url("Channel 📢", url="https://t.me/+cySPj7iDogFkMzc1"),
                                        Button.url("Group 💬", url="https://t.me/+L7tcuoCsTaMxZWVl"),
                                    ],
                                ],
                            ),
                            timeout=900,
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
                if sent_files:
                    file = sent_files[0] # Set first part for mapping
            else:
                with open(self.download, "rb") as out:
                    res = await upload_file(
                        self.client, out, self.progress_bar, self.data["file_name"]
                    )
                    await self.edit_message.edit(
                        f"⏳ **Finalizing upload...**\n\n📁 `{self.data['file_name']}`\n\nData sent to Telegram, waiting for confirmation...\n\n__Powered by @TeraboxDownloaderINDIA__",
                        parse_mode="markdown",
                    )
                    attributes, mime_type = utils.get_attributes(
                        self.download,
                    )
                    file = await asyncio.wait_for(
                        self.client.send_file(
                            self.message.chat.id,
                            file=res,
                            caption=self.caption,
                            background=True,
                            reply_to=self.message.id,
                            allow_cache=True,
                            force_document=False,
                            parse_mode="markdown",
                            supports_streaming=True,
                            thumb=self.thumbnail,
                            mime_type=mime_type,
                            buttons=[
                                [
                                    Button.url(
                                        "Direct Link",
                                        url=f"https://{BOT_USERNAME}.t.me?start={self.uuid}",
                                    ),
                                ],
                                [
                                    Button.url("Channel 📢", url="https://t.me/+cySPj7iDogFkMzc1"),
                                    Button.url("Group 💬", url="https://t.me/+L7tcuoCsTaMxZWVl"),
                                ],
                            ],
                        ),
                        timeout=900,
                    )
                try:
                    os.unlink(self.download)
                except Exception:
                    pass
                try:
                    os.unlink(self.data["file_name"])
                except Exception:
                    pass
        except asyncio.TimeoutError:
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

        await self.save_forward_file(file, shorturl)

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

    async def save_forward_file(self, file, shorturl):
        forwarded_message = await self.client.forward_messages(
            PRIVATE_CHAT_ID,
            [file],
            from_peer=self.message.chat.id,
            with_my_score=True,
            background=True,
        )
        if forwarded_message[0].id:
            db.set_key(self.uuid, forwarded_message[0].id)
            db.set_key(f"mid_{forwarded_message[0].id}", self.uuid)
            if shorturl:
                db.set_key(shorturl, forwarded_message[0].id)
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
        db.set(self.message.sender_id, time.monotonic(), ex=60)
        # await self.forward_file(
        #     self.client, forwarded_message[0].id, self.message, self.edit_message
        # )

    async def send_video(self):
        self.thumbnail = download_image_to_bytesio(self.data["thumb"], "thumbnail.png")
        shorturl = extract_code_from_url(self.url)
        if not shorturl:
            return await self.edit_message.edit("Seems like your link is invalid.")

        try:
            if self.edit_message:
                await self.edit_message.delete()
        except Exception as e:
            pass
        db.set(self.message.sender_id, time.monotonic(), ex=60)
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
        return download_image_to_bytesio(self.data["thumb"], "thumbnail.png")

    @staticmethod
    async def forward_file(
        client: TelegramClient,
        file_id: int,
        message: Message,
        edit_message: UpdateEditMessage = None,
        uid: str = None,
    ):
        if edit_message:
            try:
                await edit_message.delete()
            except Exception:
                pass
        result = await client(
            GetMessagesRequest(channel=PRIVATE_CHAT_ID, id=[int(file_id)])
        )
        msg: Message = result.messages[0] if result and result.messages else None
        if not msg:
            return False
        media: Document = (
            msg.media.document if hasattr(msg, "media") and msg.media.document else None
        )
        try:
            await message.reply(
                message=msg.message,
                file=media,
                # entity=msg.entities,
                background=True,
                reply_to=message.id,
                force_document=False,
                buttons=[
                    [
                        Button.url(
                            "Direct Link",
                            url=f"https://{BOT_USERNAME}.t.me?start={uid}",
                        ),
                    ],
                    # [
                    #     Button.url("Channel ", url="https://t.me/RoldexVerse"),
                    #     Button.url("Group ", url="https://t.me/RoldexVerseChats"),
                    # ],
                ],
                parse_mode="markdown",
            )
            db.set(message.sender_id, time.monotonic(), ex=60)
            db.incr(
                f"check_{message.sender_id}",
                1,
            )
            return True
        except Exception:
            return False

