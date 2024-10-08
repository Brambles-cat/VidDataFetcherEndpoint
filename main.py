import hashlib
from fastapi import FastAPI
from yt_dlp.YoutubeDL import YoutubeDL
from urllib.parse import urlparse, parse_qs, ParseResult
from googleapiclient.discovery import build
from dotenv import load_dotenv
import re, os

load_dotenv()
api_key = os.getenv("apikey")

# Define the options to use specific extractors
ydl_opts = {
    "allowed_extractors": ["twitter", "Newgrounds", "lbry", "TikTok", "PeerTube", "vimeo", "BiliBili", "dailymotion", "generic"]
}

yt = build("youtube", "v3", developerKey=api_key)

def extract_video_id(url_components):
    """Given a YouTube video URL, extract the video id from it, or None if
    no video id can be extracted."""
    video_id = None

    path = url_components.path
    query_params = parse_qs(url_components.query)

    # Regular YouTube URL: eg. https://www.youtube.com/watch?v=9RT4lfvVFhA
    if path == "/watch":
        video_id = query_params["v"][0]
    else:
        livestream_match = re.match("^/live/([a-zA-Z0-9_-]+)", path)
        shortened_match = re.match("^/([a-zA-Z0-9_-]+)", path)

        if livestream_match:
            # Livestream URL: eg. https://www.youtube.com/live/Q8k4UTf8jiI
            video_id = livestream_match.group(1)
        elif shortened_match:
            # Shortened YouTube URL: eg. https://youtu.be/9RT4lfvVFhA
            video_id = shortened_match.group(1)

    return video_id

def fetch_youtube(url_components):
    video_id = extract_video_id(url_components)
    request = yt.videos().list(
        part="status,snippet,contentDetails", id=video_id
    )
    response = request.execute()

    if not response["items"]:
        return None

    response_item = response["items"][0]
    snippet = response_item["snippet"]
    iso8601_duration = response_item["contentDetails"]["duration"]

    return {
        "title": snippet["title"],
        "uploader": snippet["channelTitle"],
        "upload_date": snippet["publishedAt"],
        "duration": iso8601_duration
    }

def fetch_ytdlp(url):
    preprocess_changes = preprocess(url)

    if preprocess_changes and preprocess_changes.get("url"):
        url = preprocess_changes.pop("url")

    with YoutubeDL(ydl_opts) as ydl:
        response = ydl.extract_info(url, download=False)
        if "entries" in response:
            response = response["entries"][0]

    # preprocess_changes contains the response key that should be assigned a new value,
    # and corrected, which can either be a different response key that has the value we
    # originally wanted, None if the response key has an incorrect value with no substitutes,
    # or a lambda function that modifies the value assigned to the respose key
        if len(preprocess_changes):
            for response_key, corrected in preprocess_changes.items():
                if corrected is None:
                    response[response_key] = None
                elif isinstance(corrected, str):
                    response[response_key] = response.get(corrected)
                else:
                    response[response_key] = corrected(response)

        return {
            "title": response.get("title"),
            "uploader": response.get("channel"),
            "upload_date": response.get("upload_date"),
            "duration": response.get("duration"),
        }

# Some urls might have specific issues that should
# be handled here before they can be properly processed
# If yt-dlp gets any updates that resolve any of these issues
# then the respective case should be updated accordingly
def preprocess(url: str) -> dict:
    url_components = urlparse(url)
    site = url_components.netloc.split(".")[0]
    changes = {}

    match site:
        case "x":
            url = "https://twitter.com" + url_components.path
            changes = preprocess(url)
            changes["url"] = url

        case "twitter":
            changes["channel"] = "uploader_id"
            changes["title"] = (
                lambda vid_data: f"X post by {vid_data.get('uploader_id')} ({hash_str(vid_data.get('title'))})"
            )

            # This type of url means that the post has more than one video
            # and ytdlp will only successfully retrieve the duration if
            # the video is at index one
            if (
                url[0 : url.rfind("/")].endswith("/video")
                and int(url[url.rfind("/") + 1 :]) != 1
            ):
                changes["duration"] = None

        case "newgrounds":
            changes["channel"] = "uploader"

        case "tiktok":
            changes["channel"] = "uploader"
            changes["title"] = (
                lambda vid_data: f"Tiktok video by {vid_data.get('uploader')} ({hash_str(vid_data.get('title'))})"
            )

        case "bilibili":
            changes["channel"] = "uploader"

    return changes

# Some sites like X and Tiktok don't have a designated place to put a title for
# posts so the 'titles' are hashed here to reduce the chance of similarity detection
# between different posts by the same uploader. Larger hash substrings decrease this chance
def hash_str(string):
    h = hashlib.sha256()
    h.update(string.encode())
    return h.hexdigest()[:5]


youtube_domains = ["m.youtube.com", "www.youtube.com", "youtube.com", "youtu.be"]

app = FastAPI()

@app.post("/fetch")
def update_item(urls: list[str]):
    urls: list[ParseResult] = [urlparse(url) for url in urls]
    return [fetch_youtube(url) if url.netloc in youtube_domains else fetch_ytdlp(url.geturl()) for url in urls]

# "[\"https://www.newgrounds.com/portal/view/759280\", \"https://twitter.com/doubleWbrothers/status/1786396472105115712\", \"https://odysee.com/@DeletedBronyVideosArchive:d/blind-reaction-review-mlp-make-your-3:0\", \"https://www.tiktok.com/@kyukenn__/video/7338022224466562309?q=my%20little%20pony\&t=1714177735482\"]"