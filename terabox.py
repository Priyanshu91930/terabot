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
        res_data = response.json() if response.content else {}

        if response.status_code != 200 or not res_data.get("list"):
            if res_data.get("code") == "MULTIPLE_FILES_NOT_ALLOWED" or (res_data.get("error") and "multiple files" in res_data.get("error").lower()):
                return {
                    "error_type": "MULTIPLE_FILES",
                    "error_message": res_data.get("error") or "This link contains multiple files or a folder. Please provide a link with a single file."
                }
            return False

        files = res_data["list"]

        # Check if files have dlinks already
        has_dlinks = any(f.get("dlink") for f in files)
        is_folder = not has_dlinks and all(f.get("status") == "folder_file" for f in files)

        if is_folder or len(files) > 1:
            return {
                "error_type": "MULTIPLE_FILES",
                "error_message": "This link contains multiple files or a folder. Please provide a link with a single file."
            }

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

