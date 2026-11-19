import asyncio
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
from config import BOT_USERNAME, SHORTLINK_API_KEY, SHORTLINK_API_URL
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


_mongo_client = None
_entity_cache = {}


def _check_join_request_mongo(user_id, numeric_id):
    global _mongo_client
    try:
        if _mongo_client is None:
            from config import MONGODB_URI
            from pymongo import MongoClient
            _mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=1500)
        db_mongo = _mongo_client['terabox_downloader']
        join_reqs = db_mongo['joinrequests']
        
        uids = [user_id, str(user_id)]
        raw_num = str(numeric_id).replace("-100", "").replace("-", "")
        cids = [
            numeric_id, 
            str(numeric_id), 
            int(f"-100{raw_num}"), 
            str(f"-100{raw_num}"),
            int(raw_num),
            str(raw_num)
        ]
        
        req = join_reqs.find_one({
            "userId": {"$in": uids},
            "chatId": {"$in": cids},
            "status": "pending"
        })
        return bool(req)
    except Exception as e:
        print(f"Error checking MongoDB JoinRequest: {e}")
        return False


async def is_user_on_chat(bot: TelegramClient, chat_id, user_id, chat_link: str = None) -> bool:
    """
    Check if a user is present in a specific chat, either as a member or having a pending join request.
    Handles raw numeric IDs, public @usernames, invite links, and caches access hashes safely.
    """
    if not user_id:
        return False
    if hasattr(user_id, 'user_id'):
        user_id = user_id.user_id
    elif hasattr(user_id, 'id'):
        user_id = user_id.id
    try:
        user_id = int(user_id)
    except Exception:
        pass

    # 1. First check pending join request in MongoDB (Fastest & 100% reliable for Join Request channels)
    numeric_id = None
    try:
        raw_id_str = str(chat_id).replace("-100", "").replace("-", "")
        clean_int = int(raw_id_str)
        numeric_id = int(f"-100{clean_int}")
    except Exception:
        pass

    if numeric_id:
        loop = asyncio.get_running_loop()
        req_found = await loop.run_in_executor(None, _check_join_request_mongo, user_id, numeric_id)
        if req_found:
            return True

    cache_key = f"{id(bot)}_{chat_id}_{chat_link}"
    target_entity = _entity_cache.get(cache_key)
    link_str = str(chat_link or chat_id or "")

    # 2. Resolve Target Entity if not already cached
    if not target_entity:
        # Priority A: Public username link (e.g. https://t.me/TeraboxDownloaderINDIA)
        if "t.me/" in link_str and "+" not in link_str and "joinchat/" not in link_str:
            uname = link_str.split("t.me/")[-1].strip("/").strip()
            if uname:
                try:
                    target_entity = await bot.get_entity(f"@{uname}")
                    _entity_cache[cache_key] = target_entity
                except Exception:
                    pass

        # Priority B: Direct chat_id lookup
        if not target_entity and chat_id:
            try:
                target_entity = await bot.get_entity(chat_id)
                _entity_cache[cache_key] = target_entity
            except Exception:
                try:
                    from telethon.tl.types import PeerChannel
                    cid_str = str(chat_id).replace("-100", "").replace("-", "")
                    target_entity = await bot.get_entity(PeerChannel(int(cid_str)))
                    _entity_cache[cache_key] = target_entity
                except Exception:
                    pass

    # Fallback to chat_id if target_entity still unresolved
    if not target_entity:
        target_entity = chat_id

    # 3. Check Direct Member using GetParticipantRequest & get_permissions
    is_confirmed_not_member = False
    try:
        from telethon.tl.functions.channels import GetParticipantRequest
        from telethon.errors import UserNotParticipantError, ChatAdminRequiredError, ChannelPrivateError
        
        res = await bot(GetParticipantRequest(target_entity, user_id))
        if res and hasattr(res, 'participant'):
            return True
    except UserNotParticipantError:
        # Telegram verified: User is explicitly NOT a member of this chat
        is_confirmed_not_member = True
    except (ChatAdminRequiredError, ChannelPrivateError) as admin_err:
        bot_uname = getattr(bot, 'bot_username', 'bot')
        print(f"⚠️ [FORCE SUB WARNING] Bot @{bot_uname} lacks Admin privileges in {target_entity} ({admin_err})! Please promote bot to ADMIN in this channel.")
        # If bot cannot check because it lacks admin rights, do NOT falsely block legitimate users!
        return True
    except Exception as e:
        # Try fallback to get_permissions
        try:
            from telethon.errors import UserNotParticipantError, ChatAdminRequiredError
            perms = await bot.get_permissions(target_entity, user_id)
            if perms is not None:
                return True
        except UserNotParticipantError:
            is_confirmed_not_member = True
        except ChatAdminRequiredError:
            return True
        except Exception:
            pass

    return False


async def download_file(
    url: str,
    filename: str,
    callback=None,
    headers=None,
) -> str | bool:
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid download URL provided: '{url}'")
    try:
        if not headers:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Encoding": "identity",
            }

        def _stream_download():
            session = requests.Session()
            response = session.get(url, stream=True, headers=headers, timeout=60)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))

            chunk_size = 4 * 1024 * 1024  # 4 MB chunks for high-speed streaming
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        yield f.tell(), total_size

        def _get_next_chunk(generator):
            try:
                return next(generator)
            except StopIteration:
                return None

        loop = asyncio.get_running_loop()
        gen = _stream_download()

        while True:
            res = await loop.run_in_executor(None, _get_next_chunk, gen)
            if res is None:
                break
            downloaded_size, total_size = res
            if callback:
                await callback(downloaded_size, total_size, "Downloading")

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
    bot_username: str = None,
):
    try:
        import time
        uid = str(uuid.uuid4())
        created_at = time.time()
        api_key = SHORTLINK_API_KEY
        bot_uname = bot_username or BOT_USERNAME
        # If API key is empty, bypass ad shortener and return direct activation link
        if not api_key:
            url = f"https://t.me/{bot_uname}?start=token_{uid}"
            db.set(f"token_{uid}", f"{sender_id}|{url}|{created_at}", ex=21600)
            return url

        endpoints = [SHORTLINK_API_URL, "https://vplink.in/api", "https://vplinks.in/api"]
        for api_endpoint in endpoints:
            if not api_endpoint:
                continue
            try:
                data = requests.get(
                    api_endpoint,
                    params={
                        "api": api_key,
                        "url": f"https://t.me/{bot_uname}?start=token_{uid}",
                        "alias": uid.split("-", maxsplit=2)[0],
                    },
                    timeout=10
                )
                if data.status_code == 200:
                    data_json = data.json()
                    if data_json.get("status") == "success" and data_json.get("shortenedUrl"):
                        url = data_json.get("shortenedUrl")
                        db.set(f"token_{uid}", f"{sender_id}|{url}|{created_at}", ex=21600)
                        return url
            except Exception as api_err:
                print(f"Ad shortener API error for {api_endpoint}: {api_err}")

        # Fallback to direct activation link
        url = f"https://t.me/{bot_uname}?start=token_{uid}"
        db.set(f"token_{uid}", f"{sender_id}|{url}|{created_at}", ex=21600)
        return url
    except Exception as e:
        print(f"Error in generate_shortenedUrl: {e}")
        return None
