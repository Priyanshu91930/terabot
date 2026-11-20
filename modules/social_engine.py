import os
import glob
import uuid
import time
import shutil
import logging
import asyncio
from typing import Optional, Dict, Any

from telethon import Button
from telethon.tl.types import DocumentAttributeVideo
from config import UPDATE_CHANNEL_URL

log = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.getcwd(), "downloads", "social")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def _sync_ytdlp_download(url: str, request_id: str) -> Dict[str, Any]:
    try:
        import yt_dlp
    except ImportError:
        return {"success": False, "error": "yt-dlp is not installed on this VPS! Run: pip install yt-dlp"}

    out_folder = os.path.join(DOWNLOADS_DIR, request_id)
    os.makedirs(out_folder, exist_ok=True)
    out_tmpl = os.path.join(out_folder, "%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": out_tmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 2000 * 1024 * 1024, # 2 GB Telegram Limit
        "socket_timeout": 30,
        "writethumbnail": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return {"success": False, "error": "Could not extract media info."}

            title = info.get("title") or "Downloaded Media"
            duration = int(info.get("duration") or 0)
            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)

            # Find downloaded media files
            all_files = glob.glob(os.path.join(out_folder, "*"))
            media_files = [f for f in all_files if not f.endswith(('.jpg', '.webp', '.png', '.json', '.part'))]
            thumb_files = [f for f in all_files if f.endswith(('.jpg', '.webp', '.png'))]

            if not media_files and thumb_files:
                # If only image was downloaded (e.g. Pinterest image pin or Instagram photo)
                media_files = thumb_files
                thumb_files = []

            if not media_files:
                return {"success": False, "error": "No media file could be downloaded."}

            primary_file = media_files[0]
            thumb_file = thumb_files[0] if thumb_files else None

            is_video = primary_file.lower().endswith(('.mp4', '.mkv', '.webm', '.mov', '.avi'))
            is_image = primary_file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))

            return {
                "success": True,
                "folder": out_folder,
                "file_path": primary_file,
                "thumb_path": thumb_file,
                "title": title,
                "is_video": is_video,
                "is_image": is_image,
                "duration": duration,
                "width": width,
                "height": height,
                "filesize": os.path.getsize(primary_file),
            }

    except Exception as e:
        log.error(f"[yt-dlp] Download error for {url}: {e}")
        # Clean up failed folder
        shutil.rmtree(out_folder, ignore_errors=True)
        return {"success": False, "error": str(e)}


def _sync_api_download(platform: str, url: str, request_id: str) -> Dict[str, Any]:
    from config import SOCIAL_API_BASE, YOUTUBE_API_BASE
    import html
    import requests

    if platform == "youtube":
        endpoint = f"{YOUTUBE_API_BASE}/api/download/youtube"
    else:
        endpoint = f"{SOCIAL_API_BASE}/api/download/{platform}"
    out_folder = os.path.join(DOWNLOADS_DIR, request_id)
    os.makedirs(out_folder, exist_ok=True)
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
        params = {"url": url}
        
        # Step 1: Call Cloudflare Worker API
        resp = requests.get(endpoint, params=params, headers=headers, timeout=25, stream=True)
        
        # Direct stream or 302 redirect to CDN
        content_type = resp.headers.get("content-type", "").lower()
        if "video" in content_type or "image" in content_type or "octet-stream" in content_type:
            ext = ".mp4" if "video" in content_type else (".jpg" if "image" in content_type else ".mp4")
            out_file = os.path.join(out_folder, f"media{ext}")
            with open(out_file, "wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
            return {
                "success": True,
                "folder": out_folder,
                "file_path": out_file,
                "title": f"{platform.title()} Media",
                "is_video": "video" in content_type or ext == ".mp4",
                "is_image": "image" in content_type,
                "filesize": os.path.getsize(out_file)
            }
            
        data = resp.json() if resp.content else {}
        
        # Check API failure
        if isinstance(data, dict) and data.get("success") is False:
            err_msg = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
            log.warning(f"[API] Error response for {url}: {err_msg}")
            return _sync_ytdlp_download(url, request_id)

        download_url = None
        media_type = "video"
        title = f"{platform.title()} Media"
        thumb_url = None

        if isinstance(data, dict):
            # Parse from Cloudflare Worker 'normalized' structure
            norm = data.get("normalized") or {}
            if norm:
                title = norm.get("title") or title
                thumb_url = norm.get("thumbnail")
                media_list = norm.get("media") or []
                if media_list and isinstance(media_list, list):
                    first_media = media_list[0]
                    download_url = first_media.get("url")
                    media_type = first_media.get("type", "video")

            # Parse from Cloudflare Worker 'result' structure
            if not download_url:
                res_obj = data.get("result") or {}
                if isinstance(res_obj, dict):
                    title = res_obj.get("title") or title
                    thumb_url = res_obj.get("thumbnail") or thumb_url
                    inner_res = res_obj.get("result") or {}
                    if isinstance(inner_res, dict):
                        download_url = inner_res.get("video")
                        media_type = inner_res.get("type", "video")
                        if not download_url:
                            inner_media = inner_res.get("media") or []
                            if inner_media and isinstance(inner_media, list):
                                download_url = inner_media[0].get("url")
                                media_type = inner_media[0].get("type", media_type)

            # Fallback to direct keys
            if not download_url:
                download_url = (data.get("download_url") or 
                                data.get("url") or 
                                data.get("video_url") or 
                                data.get("media"))

        if download_url:
            title = html.unescape(title)
            referer = "https://www.youtube.com/" if platform == "youtube" else ("https://www.instagram.com/" if platform in ["instagram", "threads"] else "https://www.pinterest.com/")
            media_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Referer": referer
            }
            media_resp = requests.get(download_url, headers=media_headers, stream=True, timeout=40)
            c_type = media_resp.headers.get("content-type", "").lower()
            
            is_video = (media_type == "video" or "video" in c_type or ".mp4" in download_url.lower())
            ext = ".mp4" if is_video else ".jpg"
            out_file = os.path.join(out_folder, f"media{ext}")
            
            with open(out_file, "wb") as f:
                for chunk in media_resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        
            thumb_path = None
            if thumb_url and is_video:
                try:
                    thumb_resp = requests.get(thumb_url, headers=media_headers, timeout=10)
                    if thumb_resp.status_code == 200:
                        thumb_path = os.path.join(out_folder, "thumb.jpg")
                        with open(thumb_path, "wb") as tf:
                            tf.write(thumb_resp.content)
                except Exception:
                    pass

            return {
                "success": True,
                "folder": out_folder,
                "file_path": out_file,
                "thumb_path": thumb_path,
                "title": title,
                "is_video": is_video,
                "is_image": not is_video,
                "filesize": os.path.getsize(out_file)
            }

    except Exception as e:
        log.warning(f"[API] Error downloading via API ({platform}): {e}")
        shutil.rmtree(out_folder, ignore_errors=True)
    
    # Seamless Fallback to local yt-dlp if API fails
    log.info(f"Falling back to yt-dlp extractor for {platform}...")
    return _sync_ytdlp_download(url, request_id)


async def download_media_async(url: str, platform: str = None, status_msg=None) -> Dict[str, Any]:
    """Runs API download (with automatic yt-dlp fallback), StorageGuard safety, and concurrency semaphore."""
    from modules.common import StorageGuard, GLOBAL_DOWNLOAD_SEMAPHORE
    
    if not StorageGuard.is_safe_to_download():
        return {"success": False, "error": "Server storage temporarily full. Auto-cleaner running, please try again in 1 minute."}

    if GLOBAL_DOWNLOAD_SEMAPHORE.locked() and status_msg:
        try:
            await status_msg.edit("⏳ **In Download Queue...**\n\nServer is currently processing active requests. Your turn will start in a few seconds! ⚡")
        except Exception:
            pass

    async with GLOBAL_DOWNLOAD_SEMAPHORE:
        if status_msg:
            try:
                await status_msg.edit("⚡ **Turn Arrived! Downloading media...**")
            except Exception:
                pass
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        
        # For instagram, threads, pinterest, youtube: Call API first!
        if platform in ["instagram", "threads", "pinterest", "youtube"]:
            return await loop.run_in_executor(None, _sync_api_download, platform, url, request_id)
        else:
            return await loop.run_in_executor(None, _sync_ytdlp_download, url, request_id)


async def send_downloaded_media(
    client,
    chat_id: int,
    media_info: Dict[str, Any],
    platform_name: str,
    reply_to: Optional[int] = None
):
    """Sends the downloaded video or photo to user and cleans up disk space."""
    file_path = media_info.get("file_path")
    thumb_path = media_info.get("thumb_path")
    folder = media_info.get("folder")
    title = media_info.get("title", "Media")
    is_video = media_info.get("is_video", True)
    duration = media_info.get("duration", 0)
    width = media_info.get("width", 0)
    height = media_info.get("height", 0)

    caption = (
        f"🎬 **{platform_name} Download**\n\n"
        f"📝 **Title:** `{title[:80]}`\n\n"
        f"📢 @TeraboxDownloaderINDIA"
    )

    buttons = [
        [
            Button.url("Join Channel 📢", url="https://t.me/TeraboxDownloaderINDIA"),
            Button.url("Join Group 💬", url="https://t.me/+L7tcuoCsTaMxZWVl"),
        ]
    ]

    try:
        if is_video:
            attributes = []
            if duration:
                attributes.append(DocumentAttributeVideo(
                    duration=duration,
                    w=width,
                    h=height,
                    supports_streaming=True
                ))
            
            await client.send_file(
                chat_id,
                file=file_path,
                caption=caption,
                parse_mode="markdown",
                thumb=thumb_path if (thumb_path and os.path.exists(thumb_path)) else None,
                attributes=attributes,
                supports_streaming=True,
                reply_to=reply_to,
                buttons=buttons
            )
        else:
            await client.send_file(
                chat_id,
                file=file_path,
                caption=caption,
                parse_mode="markdown",
                reply_to=reply_to,
                buttons=buttons
            )
    finally:
        # Immediately remove downloaded media folder to free up VPS disk space
        if folder and os.path.exists(folder):
            try:
                shutil.rmtree(folder, ignore_errors=True)
            except Exception as ce:
                log.warning(f"Failed to cleanup {folder}: {ce}")
