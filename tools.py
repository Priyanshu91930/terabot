import os
import re
import traceback
import uuid
from contextlib import suppress
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image
from telethon import TelegramClient

from config import BOT_USERNAME, PUBLIC_EARN_API
from redis_db import db


def check_url_patterns(url: str) -> bool:
    """
    Check if the given URL matches any of the known URL patterns for terabox and its domains.
    """
    url_lower = url.lower()
    keywords = ["terabox", "nephobox", "mirrobox", "momerybox", "4funbox", "1024tera", "tibibox", "tibbox", "terashare", "freeterabox", "dubox"]
    for keyword in keywords:
        if keyword in url_lower:
            return True
    return False


def extract_code_from_url(url: str) -> str | None:
    """
    Extracts the code from a URL.

    Parameters:
        url (str): The URL to extract the code from.

    Returns:
        str: The extracted code, or None if the URL does not contain a code.
    """
    pattern1 = r"/s/(\w+)"
    pattern2 = r"surl=(\w+)"

    match = re.search(pattern1, url)
    if match:
        return match.group(1)

    match = re.search(pattern2, url)
    if match:
        return match.group(1)

    return None


def get_urls_from_string(string: str) -> str | None:
    """
    Extracts all URLs from a given string.

    Parameters:
    string (str): The input string.

    Returns:
    str: The first URL found in the input string, or None if no URLs were found.
    """
    pattern = r"(https?://\S+)"
    urls = re.findall(pattern, string)
    if not urls:
        return None
    return urls[0]


def extract_surl_from_url(url: str) -> str:
    """
    Extracts the surl from a URL.

    Parameters:
        url (str): The URL to extract the surl from.

    Returns:
        str: The extracted surl, or None if the URL does not contain a surl.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    surl = query_params.get("surl", [])

    if surl:
        return surl[0]
    else:
        return False


def get_formatted_size(size_bytes: int) -> str:
    """
    Returns a human-readable file size from the given number of bytes.
    """
    if size_bytes >= 1024 * 1024 * 1024 * 1024:
        size = size_bytes / (1024 * 1024 * 1024 * 1024)
        unit = "GB"  # actually TB, wait.
        # Wait, 1024^4 is TB. Let's name it TB.
        unit = "TB"
    elif size_bytes >= 1024 * 1024 * 1024:
        size = size_bytes / (1024 * 1024 * 1024)
        unit = "GB"
    elif size_bytes >= 1024 * 1024:
        size = size_bytes / (1024 * 1024)
        unit = "MB"
    elif size_bytes >= 1024:
        size = size_bytes / 1024
        unit = "KB"
    else:
        size = size_bytes
        unit = "B"

    return f"{size:.2f} {unit}"


def convert_seconds(seconds: int) -> str:
    """
    Convert seconds into a human-readable format.

    Parameters:
        seconds (int): The number of seconds to convert.

    Returns:
        str: The seconds converted to a human-readable format.
    """
    seconds = int(seconds)
    hours = seconds // 3600
    remaining_seconds = seconds % 3600
    minutes = remaining_seconds // 60
    remaining_seconds_final = remaining_seconds % 60

    if hours > 0:
        return f"{hours}h:{minutes}m:{remaining_seconds_final}s"
    elif minutes > 0:
        return f"{minutes}m:{remaining_seconds_final}s"
    else:
        return f"{remaining_seconds_final}s"


async def is_user_on_chat(bot: TelegramClient, chat_id: str, user_id: int) -> bool:
    """
    Check if a user is present in a specific chat, either as a member or having a pending join request.
    """
    target_entity = chat_id
    
    # If chat_id is a private join/invite link, resolve the underlying chat/channel entity
    if "t.me/" in str(chat_id) or "+" in str(chat_id):
        try:
            target_entity = await bot.get_entity(chat_id)
        except Exception as e:
            print(f"Error resolving invite link via get_entity: {e}")
            try:
                hash_val = str(chat_id).split("+")[-1] if "+" in str(chat_id) else str(chat_id).split("joinchat/")[-1]
                hash_val = hash_val.strip("/")
                
                from telethon.tl.functions.messages import CheckChatInviteRequest
                from telethon.tl.types import ChatInviteAlready
                
                invite_info = await bot(CheckChatInviteRequest(hash_val))
                if isinstance(invite_info, ChatInviteAlready):
                    target_entity = invite_info.chat
                else:
                    target_entity = invite_info
            except Exception as ex:
                print(f"Error resolving invite link: {ex}")

    # 1. Check direct channel membership via Telethon participant check
    try:
        from telethon.errors import UserNotParticipantError
        await bot.get_permissions(target_entity, user_id)
        return True
    except UserNotParticipantError:
        pass
    except Exception as e:
        print(f"DEBUG: get_permissions failed for chat {target_entity} user {user_id}: {e}")
        pass

    # 2. Check pending join request in MongoDB (Join Request Mode)
    try:
        from config import MONGODB_URI
        from pymongo import MongoClient
        
        # Resolve target channel to obtain its numeric ID (e.g. -100xxxxxxxxxx)
        entity = await bot.get_input_entity(target_entity)
        if hasattr(entity, 'channel_id'):
            numeric_id = int(f"-100{entity.channel_id}")
        elif hasattr(entity, 'chat_id'):
            numeric_id = int(f"-100{entity.chat_id}")
        elif hasattr(entity, 'id'):
            numeric_id = int(f"-100{entity.id}")
        else:
            return False
            
        client = MongoClient(MONGODB_URI)
        db = client.get_default_database()
        if db is None or db.name == 'test':
            db = client['terabox_downloader']
            
        join_reqs = db['joinrequests']
        
        # Look for a pending join request matching this user and channel
        req = join_reqs.find_one({
            "userId": user_id,
            "chatId": numeric_id,
            "status": "pending"
        })
        if req:
            return True
    except Exception as e:
        print(f"Error checking MongoDB JoinRequest: {e}")
        
    return False


async def download_file(
    url: str,
    filename: str,
    callback=None,
    headers=None,
) -> str | bool:
    try:
        if not headers:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        response = requests.get(url, stream=True, headers=headers, timeout=45)
        response.raise_for_status()
        with suppress(
            requests.exceptions.ChunkedEncodingError,
        ):
            with open(filename, "wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    file.write(chunk)
                    if callback:
                        downloaded_size = file.tell()
                        total_size = int(
                            response.headers.get("content-length", 0))
                        await callback(downloaded_size, total_size, "Downloading")
        # await asyncio.sleep(2)
        return filename
    except Exception as e:
        traceback.print_exc()
        print(f"Error downloading file: {e}")
        raise Exception(e)


def save_image_from_bytesio(image_bytesio, filename):
    try:
        image_bytesio.seek(0)
        image = Image.open(image_bytesio)
        image.save(filename)
        image.close()

        return filename

    except Exception as e:
        print(f"Error saving image: {e}")
        return False


def download_image_to_bytesio(url: str, filename: str) -> BytesIO | None:
    """
    Downloads an image from a URL and returns it as a BytesIO object.

    Args:
        url (str): The URL of the image to download.
        filename (str): The filename to save the image as.

    Returns:
        BytesIO: The image data as a BytesIO object, or None if the download failed.
    """
    try:
        response = requests.get(url)
        content = BytesIO()
        content.name = filename
        if response.status_code == 200:
            for chunk in response.iter_content(chunk_size=1024):
                content.write(chunk)
        else:
            return None
        content.seek(0)
        return content
    except Exception:
        return None


def remove_all_videos():
    current_directory = os.getcwd()

    video_extensions = [".mp4", ".mkv", ".webm"]

    try:
        for file_name in os.listdir(current_directory):
            if any(file_name.lower().endswith(ext) for ext in video_extensions):
                file_path = os.path.join(current_directory, file_name)

                os.remove(file_path)

    except Exception as e:
        print(f"Error: {e}")


def generate_shortenedUrl(
    sender_id: int,
):
    try:
        uid = str(uuid.uuid4())
        # If API key is empty, bypass ad shortener and return direct activation link
        if not PUBLIC_EARN_API:
            url = f"https://t.me/{BOT_USERNAME}?start=token_{uid}"
            db.set(f"token_{uid}", f"{sender_id}|{url}", ex=21600)
            return url

        try:
            data = requests.get(
                "https://publicearn.com/api",
                params={
                    "api": PUBLIC_EARN_API,
                    "url": f"https://t.me/{BOT_USERNAME}?start=token_{uid}",
                    "alias": uid.split("-", maxsplit=2)[0],
                },
                timeout=10
            )
            data.raise_for_status()
            data_json = data.json()
            if data_json.get("status") == "success":
                url = data_json.get("shortenedUrl")
                db.set(f"token_{uid}", f"{sender_id}|{url}", ex=21600)
                return url
        except Exception as api_err:
            print(f"Ad shortener API error: {api_err}. Falling back to direct link.")

        # Fallback to direct activation link
        url = f"https://t.me/{BOT_USERNAME}?start=token_{uid}"
        db.set(f"token_{uid}", f"{sender_id}|{url}", ex=21600)
        return url
    except Exception as e:
        print(f"Error in generate_shortenedUrl: {e}")
        return None
