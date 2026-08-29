import re
import time
from pprint import pp
from urllib.parse import parse_qs, urlparse

import requests

from tools import get_formatted_size


def check_url_patterns(url):
    patterns = [
        r"terabox\.com",
        r"1024tera\.com",
        r"1024tera\.co",
        r"1024terabox\.com",
        r"terabox\.app",
        r"terabox\.ap",
        r"terabox\.fun",
        r"teraboxlink\.com",
        r"terasharelink\.com",
        r"terasharefile\.com",
        r"terashare\.com",
        r"nephobox\.com",
        r"teraboxapp\.com",
        r"mirrobox\.com",
        r"freeterabox\.com",
        r"momerybox\.com",
        r"tibbox\.com",
        r"tibibox\.com",
        r"4funbox\.com",
        r"4funbox\.co",
        r"dubox\.com",
        r"terabox\.best",
        r"teraboxshare\.com",
        r"terafileshare\.com",
        r"1024box\.com",
    ]

    for pattern in patterns:
        if re.search(pattern, url):
            return True

    return False


def get_urls_from_string(string: str) -> list[str]:
    """
    Extracts URLs from a given string.

    Args:
        string (str): The input string from which to extract URLs.

    Returns:
        list[str]: A list of URLs extracted from the input string. If no URLs are found, an empty list is returned.
    """
    pattern = r"(https?://\S+)"
    urls = re.findall(pattern, string)
    urls = [url for url in urls if check_url_patterns(url)]
    if not urls:
        return []
    return urls[0]


def find_between(data: str, first: str, last: str) -> str | None:
    """
    Searches for the first occurrence of the `first` string in `data`,
    and returns the text between the two strings.

    Args:
        data (str): The input string.
        first (str): The first string to search for.
        last (str): The last string to search for.

    Returns:
        str | None: The text between the two strings, or None if the
            `first` string was not found in `data`.
    """
    try:
        start = data.index(first) + len(first)
        end = data.index(last, start)
        return data[start:end]
    except ValueError:
        return None


def extract_surl_from_url(url: str) -> str | None:
    """
    Extracts the surl parameter from a given URL.

    Args:
        url (str): The URL from which to extract the surl parameter.

    Returns:
        str: The surl parameter, or False if the parameter could not be found.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    surl = query_params.get("surl", [])

    if surl:
        return surl[0]
    else:
        return False


def parse_size_to_bytes(size_str: str) -> int:
    try:
        size_str = size_str.upper().strip()
        match = re.match(r"([0-9.]+)\s*([A-Z]+)", size_str)
        if not match:
            return 0
        value = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 * 1024,
            "GB": 1024 * 1024 * 1024,
            "TB": 1024 * 1024 * 1024 * 1024,
            "BYTES": 1,
        }
        return int(value * multipliers.get(unit, 1))
    except Exception:
        return 0


def get_data(url: str):
    from config import TERABOX_API_BASE, TERABOX_API_KEY
    api_url = f"{TERABOX_API_BASE}/parse"
    api_key = TERABOX_API_KEY
    
    try:
        response = requests.get(api_url, params={"url": url, "apiKey": api_key, "from": "bot"}, timeout=25)
        if response.status_code != 200:
            return False
            
        res_data = response.json()
        if not res_data.get("list"):
            return False

        files = res_data["list"]

        # Check if files have dlinks already (folder-expanded with dlinks resolved)
        has_dlinks = any(f.get("dlink") for f in files)

        # Detect folder link: all files have status='folder_file' and NO dlinks
        is_folder = not has_dlinks and all(f.get("status") == "folder_file" for f in files)

        if is_folder:
            share_id = res_data.get("listData_share_id")
            uk = res_data.get("listData_uk")
            headers = res_data.get("downloadHeaders")
            download_headers = res_data.get("downloadHeaders")

            # Return all files WITHOUT dlinks - bot will fetch on-demand during upload
            all_files = []
            for f in files:
                size_str = f.get("size", "0 B")
                size_bytes = parse_size_to_bytes(size_str)
                all_files.append({
                    "file_name": f.get("name") or "file",
                    "fs_id": f.get("fs_id"),
                    "link": f.get("dlink") or "",
                    "direct_link": f.get("dlink") or "",
                    "thumb": f.get("thumbnail", ""),
                    "size": size_str,
                    "sizebytes": size_bytes,
                    "headers": download_headers,
                    "share_id": share_id,
                    "uk": uk,
                })

            if all_files:
                print(f"[FOLDER] Returning {len(all_files)} files (dlinks fetched on-demand)")
                return {"is_folder": True, "files": all_files, "total_files": len(all_files)}

            return {
                "file_name": files[0].get("name") if files else "folder",
                "link": None, "direct_link": None, "thumb": "",
                "size": "0 B", "sizebytes": 0, "headers": headers,
                "is_folder": True, "total_files": len(files),
            }

            if all_files:
                return {"is_folder": True, "files": all_files, "total_files": len(all_files)}

            # Fallback: just return folder info with no download
            return {
                "file_name": files[0].get("name") if files else "folder",
                "link": None,
                "direct_link": None,
                "thumb": "",
                "size": "0 B",
                "sizebytes": 0,
                "headers": headers,
                "is_folder": True,
                "total_files": len(files),
            }

        # Normal single/multi file (non-folder)
        file_info = files[0]
        size_str = file_info.get("size", "0 B")
        size_bytes = parse_size_to_bytes(size_str)
        thumb = file_info.get("thumbnail")
        data = {
            "file_name": file_info.get("name") or "video.mp4",
            "link": file_info.get("dlink"),
            "direct_link": file_info.get("dlink"),
            "thumb": thumb,
            "size": size_str,
            "sizebytes": size_bytes,
            "headers": res_data.get("downloadHeaders"),
        }
        print(f"[DEBUG] Download URL: {data['direct_link'][:120] if data['direct_link'] else 'NONE'}...")
        return data
    except Exception as e:
        print(f"Error calling Vercel API: {e}")
        return False

