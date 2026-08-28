import re
from pprint import pp
from urllib.parse import parse_qs, urlparse

import requests

from tools import get_formatted_size


def check_url_patterns(url):
    patterns = [
        r"ww\.mirrobox\.com",
        r"www\.nephobox\.com",
        r"freeterabox\.com",
        r"www\.freeterabox\.com",
        r"1024tera\.com",
        r"4funbox\.co",
        r"www\.4funbox\.com",
        r"mirrobox\.com",
        r"nephobox\.com",
        r"terabox\.app",
        r"terabox\.com",
        r"www\.terabox\.ap",
        r"www\.terabox\.com",
        r"www\.1024tera\.co",
        r"www\.momerybox\.com",
        r"teraboxapp\.com",
        r"momerybox\.com",
        r"tibibox\.com",
        r"www\.tibibox\.com",
        r"www\.teraboxapp\.com",
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


def get_data(url: str):
    from config import TERABOX_API_BASE, TERABOX_API_KEY
    api_url = f"{TERABOX_API_BASE}/parse"
    api_key = TERABOX_API_KEY
    
    try:
        response = requests.get(api_url, params={"url": url, "apiKey": api_key}, timeout=20)
        if response.status_code != 200:
            return False
            
        res_data = response.json()
        if not res_data.get("success") or not res_data.get("files"):
            return False
            
        file_info = res_data["files"][0]
        size_bytes = int(file_info.get("size", 0))
        
        # Check if thumbnail is available
        thumb = file_info.get("thumbnail")
        
        data = {
            "file_name": file_info.get("name") or "video.mp4",
            "link": file_info.get("dlink"),
            "direct_link": file_info.get("dlink"),
            "thumb": thumb,
            "size": file_info.get("size_formatted") or get_formatted_size(size_bytes),
            "sizebytes": size_bytes,
        }
        return data
    except Exception as e:
        print(f"Error calling Vercel API: {e}")
        return False
