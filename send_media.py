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

@RoldexVerse
            """
        self.caption2 = f"""
Downloading `{self.data['file_name']}`
Size: **{self.data["size"]}**

@RoldexVerse
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

__Powered by @RoldexVerse__
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
        try:
            with open(self.download, "rb") as out:
                res = await upload_file(
                    self.client, out, self.progress_bar, self.data["file_name"]
                )
                attributes, mime_type = utils.get_attributes(
                    self.download,
                )
                file = await self.client.send_file(
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
                            Button.url("Channel ", url="https://t.me/RoldexVerse"),
                            Button.url(
                                "Group ", url="https://t.me/RoldexVerseChats"
                            ),
                        ],
                    ],
                )
            try:
                os.unlink(self.download)
            except Exception:
                pass
            try:
                os.unlink(self.data["file_name"])
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
