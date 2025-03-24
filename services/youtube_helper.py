import os
import re
import time

import requests
import subprocess
import uuid
from dotenv import load_dotenv
load_dotenv()
from fastapi import UploadFile, HTTPException

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled
)
from urllib.parse import urlparse, parse_qs
import json

from services.error_logging import log_error_once, raise_http_exception_once

proxy_username = os.getenv('PROXY_USER')
proxy_password = os.getenv('PROXY_PASSWORD')
proxy_port = os.getenv('PROXY_PORT')

proxies = {
    "http": f"http://{proxy_username}:{proxy_password}@gate.smartproxy.com:{proxy_port}",
    "https": f"https://{proxy_username}:{proxy_password}@gate.smartproxy.com:{proxy_port}"
}

def extract_video_id(url: str) -> str:
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    path = parsed_url.path

    if 'youtu.be' in domain:
        video_id = path.lstrip('/')
        if not video_id:
            raise_http_exception_once(
                Exception("No video ID in youtu.be"),
                400,
                "No video ID found in youtu.be URL.",
                "The error: No video ID found in youtu.be URL, in extract_video_id in youtube_helper.py"
            )
        return video_id

    if 'youtube.com' in domain:
        if path.startswith('/shorts/'):
            segments = path.split('/')
            if len(segments) >= 3 and segments[1] == 'shorts':
                video_id = segments[2]
                if video_id:
                    return video_id
                else:
                    raise_http_exception_once(
                        Exception("No ID in shorts path"),
                        400,
                        "No video ID found in shorts path.",
                        "The error: No video ID found in shorts path, in extract_video_id in youtube_helper.py"
                    )
            else:
                raise_http_exception_once(
                    Exception("Unexpected shorts path"),
                    400,
                    "Unexpected path format for YouTube Shorts URL.",
                    "The error: Unexpected path format for YouTube Shorts URL, in extract_video_id in youtube_helper.py"
                )

        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            return query_params['v'][0]

        raise_http_exception_once(
            Exception("No v= param"),
            400,
            "No video ID found in youtube.com URL parameters.",
            "The error: No video ID found in youtube.com URL parameters, in extract_video_id in youtube_helper.py"
        )

    raise_http_exception_once(
        Exception("Not valid YT URL"),
        400,
        "Not a valid YouTube URL.",
        "The error: Not a valid YouTube URL, in extract_video_id in youtube_helper.py"
    )

def convert_to_start_end_format(transcript_list):
    new_list = []
    for entry in transcript_list:
        start_time = entry["start"]
        end_time = start_time + entry["duration"]
        new_list.append({
            "text": entry["text"],
            "start": round(start_time, 2),
            "end": round(end_time, 2)
        })
    return new_list

def get_all_transcripts(url: str):
    video_id = extract_video_id(url)
    try:
        transcripts_obj = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    except NoTranscriptFound as e1:
        # Expected exception: no transcripts found. Do not log to Slack.
        raise NoTranscriptFound(f"No transcripts found for video ID '{video_id}'")
    except TranscriptsDisabled as e2:
        # Expected exception: transcripts are disabled. Do not log to Slack.
        raise TranscriptsDisabled(f"Transcripts are disabled for video ID '{video_id}'")
    except Exception as e3:
        # Log only unexpected errors.
        log_error_once(e3, f"The error: {str(e3)}, in get_all_transcripts in youtube_helper.py")
        raise

    all_transcripts = []
    for t in transcripts_obj:
        raw_data = t.fetch()
        converted_data = convert_to_start_end_format(raw_data)
        all_transcripts.append({
            "language": t.language,
            "language_code": t.language_code,
            "is_generated": t.is_generated,
            "is_translatable": t.is_translatable,
            "transcript": converted_data
        })
    return all_transcripts


def ensure_audio_only(file_path: str) -> str:
    """
    Checks if 'file_path' is already a single audio track with no video. 
    If it has a video track or multiple audio streams, extract just the first audio track 
    (no re-encode) into a new file (e.g. .aac, .mp3, etc.) and return that new path.
    Otherwise return the original path.
    """
    # 1) Probe the file
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", file_path
    ]
    try:
        probe_output = subprocess.check_output(probe_cmd)
        probe_data = json.loads(probe_output)
    except Exception as e:
        raise_http_exception_once(
            e,
            500,
            f"Failed to probe file: {file_path}",
            f"The error: {str(e)}, in ensure_audio_only in youtube.py"
        )

    streams = probe_data.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    # If already 1 audio stream, no video => do nothing
    if len(video_streams) == 0 and len(audio_streams) == 1:
        return file_path

    # Otherwise, we have video or multiple audio streams => extract the first audio track
    audio_codec = audio_streams[0].get("codec_name", "aac") if audio_streams else "aac"

    # Decide extension
    if audio_codec == "mp3":
        out_ext = ".mp3"
    elif audio_codec == "aac":
        out_ext = ".aac"
    else:
        # fallback
        out_ext = f".{audio_codec}"

    out_file = os.path.join("uploads", f"{uuid.uuid4().hex}{out_ext}")

    extract_cmd = [
        "ffmpeg", "-i", file_path,
        "-vn",            # remove video
        "-acodec", "copy",# copy the audio track only, no re-encode
        out_file,
        "-y"
    ]
    try:
        subprocess.run(extract_cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise_http_exception_once(
            e,
            500,
            f"FFmpeg error while extracting audio from {file_path}",
            f"The error: {str(e)}, in ensure_audio_only in youtube.py"
        )

    return out_file

# def download_youtube_audio(youtube_url: str):
#     api_url = os.getenv('YOUTUBE_API_URL')
#     querystring = {"url": youtube_url}
#     headers = {
#         "x-rapidapi-key": os.getenv('YOUTUBE_API_KEY'),
#         "x-rapidapi-host": os.getenv('YOUTUBE_API_HOST')
#     }

#     print(f"[Fallback] Requesting MP3 link via RapidAPI for {youtube_url} ...")

#     # We'll try up to 15 times in case of temporary 400 or 5xx errors
#     attempts = 15
#     for attempt in range(attempts):
#         try:
#             response = requests.get(api_url, headers=headers, params=querystring)
#             response.raise_for_status()
#             resp_json = response.json()

#             if resp_json.get("success"):
#                 download_link = resp_json.get("download")
#                 if download_link:
#                     print(download_link, "download_link====================================================")
#                     return {"download_url": download_link}
#                 else:
#                     raise_http_exception_once(
#                         Exception("No download link"),
#                         500,
#                         "Download link not found in response.",
#                         "The error: Download link not found in response, in download_youtube_audio in youtube_helper.py"
#                     )
#             else:
#                 raise_http_exception_once(
#                     Exception("API not successful"),
#                     500,
#                     "API response was not successful.",
#                     "The error: API response was not successful, in download_youtube_audio in youtube_helper.py"
#                 )

#         except requests.exceptions.RequestException as e4:
#             # If it's the last attempt, raise the error
#             if attempt == attempts - 1:
#                 raise_http_exception_once(
#                     e4,
#                     500,
#                     f"Failed to retrieve MP3 link after {attempts} attempts: {str(e4)}",
#                     f"The error: {str(e4)}, in download_youtube_audio in youtube_helper.py"
#                 )
#             else:
#                 # Otherwise, wait briefly and retry
#                 print(f"Error on attempt {attempt+1}, retrying in 2s...")
#                 time.sleep(5)

def get_all_transcripts_with_fallback(url: str):
    try:
        all_t = get_all_transcripts(url)
        return {
            "is_runpod": False,
            "is_transcript": True,
            "all_transcripts": all_t,
            "status_code": 200
        }
    except (NoTranscriptFound, TranscriptsDisabled, ValueError, Exception) as e:
        # Only log to Slack if the error is not due to missing subtitles.
        if not isinstance(e, (NoTranscriptFound, TranscriptsDisabled)):
            log_error_once(e, f"[Fallback] The error: {str(e)}, in get_all_transcripts_with_fallback in youtube_helper.py")
        print(f"[Fallback] Transcript retrieval failed ({str(e)}). Downloading audio...")

        try:
            fallback_result = download_youtube_audio(url)
            download_url = fallback_result.get("download_url", "")
            download_file_path = fallback_result["local_path"]
            return {
                "is_runpod": False,
                "is_transcript": False,
                "url": download_url,
                "local_path": download_file_path,
                "status_code": 200
            }
        except Exception as audio_error:
            log_error_once(audio_error, f"[Error] Audio download also failed: {str(audio_error)}, in get_all_transcripts_with_fallback in youtube_helper.py")
            print(f"[Error] Audio download also failed: {str(audio_error)}")
            raise HTTPException(status_code=500, detail="Failed to retrieve transcript or download audio.")




def parse_duration(duration: str) -> int:
    """
    Parses an ISO 8601 duration string (e.g., "PT1H2M3S") and returns the total seconds.
    """
    pattern = r'PT((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?'
    match = re.match(pattern, duration)
    if not match:
        return 0
    hours = int(match.group('hours')) if match.group('hours') else 0
    minutes = int(match.group('minutes')) if match.group('minutes') else 0
    seconds = int(match.group('seconds')) if match.group('seconds') else 0
    return hours * 3600 + minutes * 60 + seconds

def format_duration(total_seconds: int) -> str:
    """
    Converts total seconds into a formatted duration string.
    If there are hours, it returns hh:mm:ss, otherwise mm:ss.
    """
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

def get_video_metadata(youtube_url: str) -> dict:
    """
    Extracts video metadata (title, thumbnail URL, formatted duration, and duration in seconds)
    using the YouTube Data API.
    Requires a valid API key in the environment variable YOUTUBE_DATA_API_KEY.
    """
    video_id = extract_video_id(youtube_url)
    api_key = os.getenv("YOUTUBE_DATA_API_KEY")
    if not api_key:
        raise_http_exception_once(
            Exception("Missing API key"),
            500,
            "Missing YOUTUBE_DATA_API_KEY in environment variables.",
            "Missing API key in get_video_metadata in youtube_helper.py"
        )
    # Request both snippet and contentDetails
    api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails&id={video_id}&key={api_key}"
    response = requests.get(api_url)
    response.raise_for_status()
    data = response.json()
    if not data.get("items"):
        raise_http_exception_once(
            Exception("Video not found"),
            404,
            "Video not found via YouTube Data API.",
            "Video not found in get_video_metadata in youtube_helper.py"
        )
    item = data["items"][0]
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    title = snippet.get("title")
    thumbnails = snippet.get("thumbnails", {})
    thumbnail = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url")
    )
    duration_iso = content_details.get("duration", "PT0S")
    total_seconds = parse_duration(duration_iso)
    video_duration = format_duration(total_seconds)
    return {"title": title, "thumbnail": thumbnail, "video_duration": video_duration, "duration_seconds": total_seconds}


# CMD process -------------------------------------------------------------------

proxy_username = os.getenv('PROXY_USER')
proxy_password = os.getenv('PROXY_PASSWORD')
proxy_port = os.getenv('PROXY_PORT')

proxies = {
    "http": f"http://{proxy_username}:{proxy_password}@gate.smartproxy.com:{proxy_port}",
    "https": f"https://{proxy_username}:{proxy_password}@gate.smartproxy.com:{proxy_port}"
}

def download_youtube_audio(youtube_url: str) -> dict:
    """
    Uses yt-dlp via subprocess to:
      1) Download the best audio from the given YouTube URL.
      2) Extract audio and convert it to MP3 at ~192 kbps.
      3) Store the file in the 'uploads/' folder with a random UUID as the filename.
      4) Return a 'download_url' that points to the local file.
    """
    print(f"[yt-dlp subprocess] Attempting to download and convert audio for {youtube_url} ...")

    # Build proxy string using HTTP scheme (this often works better for HTTPS downloads)
    proxy_str = proxies.get("http")
    
    # Generate a UUID-based output template for a safe filename.
    random_uuid = uuid.uuid4().hex
    outtmpl = os.path.join("uploads", random_uuid + ".%(ext)s")

    # Build the command with the proxy and postprocessing options for MP3 conversion.
    cmd = [
        "yt-dlp",
        "--proxy", proxy_str,
        "--retries", "15",                  # Increase overall retries
        "--fragment-retries", "15",         # Retry fragment downloads
        "--socket-timeout", "90",           # Socket timeout in seconds
        "--extract-audio",
        "-f", "bestaudio[abr<=64]/worstaudio",
        "--audio-format", "aac",
        "--audio-quality", "64K",
        "-o", outtmpl,
        youtube_url
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise_http_exception_once(
            e,
            500,
            f"yt-dlp failed to download audio: {str(e)}",
            f"The error: {str(e)}, in download_youtube_audio in youtube_helper.py"
        )
    
    # Determine the final file path.
    # With the postprocessor, the output should be a .mp3 file.
    mp3_path = os.path.join("uploads", random_uuid + ".m4a")
    
    # Fallback: search for any file starting with our UUID if the expected filename doesn't exist.
    if not os.path.exists(mp3_path):
        for fname in os.listdir("uploads"):
            if fname.startswith(random_uuid):
                mp3_path = os.path.join("uploads", fname)
                break

    if not os.path.exists(mp3_path):
        raise_http_exception_once(
            Exception("Downloaded file not found"),
            500,
            "Downloaded file not found in uploads folder.",
            "The error: Downloaded file not found, in download_youtube_audio in youtube_helper.py"
        )

    # Build a domain-based URL to serve the file.
    domain_url = os.getenv('DOMAIN_URL')
    if not domain_url:
        raise_http_exception_once(
            Exception("Missing DOMAIN_URL"),
            500,
            "DOMAIN_URL is not set; cannot build final download_url.",
            "The error: DOMAIN_URL is not set, in download_youtube_audio in youtube_helper.py"
        )

    rel_path = os.path.relpath(mp3_path)  # e.g. 'uploads/<random_uuid>.mp3'
    download_url = f"{domain_url}/{rel_path}"

    return {"download_url": download_url,
           "local_path": mp3_path}

# ------------------------------------------------------------------------------
#  YT-DLP Python API approach with post-processing => MP3 + proxy
# ------------------------------------------------------------------------------
# from yt_dlp import YoutubeDL

# def download_youtube_audio(youtube_url: str) -> dict:
#     """
#     Uses the Python API of yt-dlp to:
#       1) Download the best audio
#       2) Convert to MP3 at ~192 kbps
#       3) Store in 'uploads/' with a name based on the video title
#       4) Return a 'download_url' that points to that local file
#     """

#     print(f"[yt-dlp Python API] Attempting to download and convert audio for {youtube_url} ...")

#     # Build a proxy string from 'proxies' if you want to use one
#     # (If you'd rather not proxy, remove this or set it to None)
#     proxy_str = proxies.get("https")  # or proxies["https"] as needed

#     # Build a UUID-based name for the file, ignoring the original YouTube title
#     random_uuid = uuid.uuid4().hex
#     outtmpl = os.path.join("uploads", random_uuid + ".%(ext)s")

#     ydl_opts = {
#         'format': 'bestaudio/best',
#         'outtmpl': outtmpl,
#         'postprocessors': [{
#             'key': 'FFmpegExtractAudio',
#             'preferredcodec': 'mp3',
#             'preferredquality': '192'
#         }],
#     }

#     # If you want to use the proxy:
#     if proxy_str:
#         ydl_opts['proxy'] = proxy_str
#         ydl_opts['socket_timeout'] = 20  # Increase timeout to 20 seconds (or more if needed)


#     try:
#         with YoutubeDL(ydl_opts) as ydl:
#             # 'info_dict' will have metadata including final filename
#             info_dict = ydl.extract_info(youtube_url, download=True)
#             # The postprocessor renames the file to .mp3
#             final_filepath = ydl.prepare_filename(info_dict)
#             # But it might still be .webm or .m4a if FFmpeg fails,
#             # so let's guess it's changed to .mp3 if everything worked.
#             # Usually "final_filepath" is "uploads/<title>.webm"
#             # after the initial download, but after post-processing,
#             # the extension is replaced with .mp3

#             # Let's handle the changed extension:
#             base, _ = os.path.splitext(final_filepath)
#             mp3_path = base + ".mp3"
#             if not os.path.exists(mp3_path):
#                 # fallback if the file didn't rename for some reason
#                 mp3_path = final_filepath

#             # Build a domain-based URL if needed
#             domain_url = os.getenv('DOMAIN_URL')
#             if not domain_url:
#                 raise_http_exception_once(
#                     Exception("Missing DOMAIN_URL"),
#                     500,
#                     "DOMAIN_URL is not set; cannot build final download_url.",
#                     "The error: DOMAIN_URL is not set, in download_youtube_audio in youtube_helper.py"
#                 )

#             # We'll return a local path as: domain_url/uploads/<file>.mp3
#             # But note that the <title> may contain spaces or special characters
#             # you might want to sanitize. For now we use it directly.
#             # Also ensure your server can serve files from 'uploads/'
#             rel_path = os.path.relpath(mp3_path)  # e.g. 'uploads/Some Title.mp3'
#             download_url = f"{domain_url}/{rel_path}"

#             return {"download_url": download_url}

#     except Exception as e:
#         raise_http_exception_once(
#             e,
#             500,
#             f"Failed to download or convert YouTube audio with yt-dlp Python API: {str(e)}",
#             f"The error: {str(e)}, in download_youtube_audio in youtube_helper.py"
#         )

# ----------------------------------------------------------------------------
# Use yt-dlp to get a direct streaming URL (best audio). Reduced retries + socket timeout.
# ----------------------------------------------------------------------------

# def run_command_with_timeout(cmd, timeout=10):
#     """
#     Executes a subprocess command with a timeout (in seconds).
#     Raises:
#        - subprocess.CalledProcessError on non-zero exit
#        - Exception on timeout
#     Returns:
#        stdout (string)
#     """
#     proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
#     try:
#         stdout, stderr = proc.communicate(timeout=timeout)
#         if proc.returncode != 0:
#             raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout + stderr)
#         return stdout
#     except subprocess.TimeoutExpired:
#         proc.kill()
#         raise Exception(f"Command timed out after {timeout} seconds: {' '.join(cmd)}")
    
# # =========================================================================
# # NEW Direct Download Approach with yt-dlp (Single Step)
# # =========================================================================
# def download_youtube_audio(youtube_url: str):
#     """
#     1) Directly download 'bestaudio' using yt-dlp into the 'uploads/' folder.
#     2) Return a domain-based URL to that local file so the existing code 
#        can do requests.get(...) on it.
#     """
#     print(f"[yt-dlp direct download] Attempting to download best audio for {youtube_url} ...")

#     # Prepare an output pattern in 'uploads/' with a random name
#     outfile_base = uuid.uuid4().hex
#     outfile_pattern = os.path.join("uploads", f"{outfile_base}.%(ext)s")
#     yt_proxy = proxies["https"]  

#     # We'll run yt-dlp as a subprocess
#     cmd = [
#         "yt-dlp",
#         "-f", "bestaudio/best",
#          "--proxy", yt_proxy,
#         "-o", outfile_pattern,
#         youtube_url
#     ]
#     try:
#         subprocess.run(cmd, check=True)
#     except subprocess.CalledProcessError as e4:
#         raise_http_exception_once(
#             e4,
#             500,
#             f"yt-dlp failed to download audio: {str(e4)}",
#             f"The error: {str(e4)}, in download_youtube_audio in youtube_helper.py"
#         )

#     # We need to figure out the final file name. 
#     # Typically, yt-dlp replaces '%(ext)s' with the real extension used, e.g. 'webm' or 'm4a'.
#     # Let's guess by searching for that unique prefix in 'uploads/'.

#     final_file_path = None
#     uploads_list = os.listdir("uploads")
#     for fname in uploads_list:
#         if fname.startswith(outfile_base):
#             final_file_path = os.path.join("uploads", fname)
#             break

#     if not final_file_path or not os.path.exists(final_file_path):
#         raise_http_exception_once(
#             Exception("Downloaded file not found"),
#             500,
#             "yt-dlp indicated success, but downloaded file was not found in uploads folder.",
#             "The error: Downloaded file not found, in download_youtube_audio in youtube_helper.py"
#         )

#     # Construct a domain-based URL so handle_audio_download_and_transcribe(...) can requests.get(...)
#     domain_url = os.getenv('DOMAIN_URL')
#     if not domain_url:
#         raise_http_exception_once(
#             Exception("Missing DOMAIN_URL"),
#             500,
#             "DOMAIN_URL is not set; cannot build final download_url.",
#             "The error: DOMAIN_URL is not set, in download_youtube_audio in youtube_helper.py"
#         )

#     download_url = f"{domain_url}/{final_file_path}"

#     return {"download_url": download_url}
# =========================================================================

# < ========================================================================================================================================================== >

# YouTube Downloader API - Fast, Reliable, and Easy
# def download_youtube_audio(youtube_url: str):
#     # New primary: previously the fallback API becomes the primary API.
#     new_primary_api_url = "https://youtube-downloader-api-fast-reliable-and-easy.p.rapidapi.com/fetch_audio"
#     new_primary_headers = {
#         "x-rapidapi-key": os.getenv('YOUTUBE_FALLBACK_API_KEY', "b244a264ffmsh4f12c104a873cfap102aacjsn11c7ce9b7735"),
#         "x-rapidapi-host": "youtube-downloader-api-fast-reliable-and-easy.p.rapidapi.com"
#     }
#     querystring = {"url": youtube_url}
    
#     print(f"[New Primary] Requesting audio link via fallback API (now primary) for {youtube_url} ...")
    
#     attempts = 15
#     new_primary_error = None
#     for attempt in range(attempts):
#         try:
#             response = requests.get(new_primary_api_url, headers=new_primary_headers, params=querystring)
#             response.raise_for_status()
#             fallback_json = response.json()
#             # Check for a successful response and available audio formats.
#             if fallback_json.get("status") == 200 and fallback_json.get("audio_formats"):
#                 download_link = None
#                 # Prefer an m4a format if available.
#                 for fmt in fallback_json["audio_formats"]:
#                     if fmt.get("ext") == "m4a":
#                         download_link = fmt.get("url")
#                         break
#                 # Otherwise, use the first available format.
#                 if not download_link:
#                     download_link = fallback_json["audio_formats"][0].get("url")
#                 if download_link:
#                     print(download_link, "download_link from new primary API (fallback endpoint)")
#                     return {"download_url": download_link}
#                 else:
#                     raise Exception("Download link not found in new primary API response.")
#             else:
#                 raise Exception("New primary API response was not successful.")
#         except Exception as e:
#             new_primary_error = e
#             if attempt == attempts - 1:
#                 print("New primary API failed after multiple attempts, trying old primary API as fallback.")
#             else:
#                 print(f"Error on new primary attempt {attempt+1}: {e}. Retrying in 5s...")
#                 time.sleep(5)
    
#     # Old primary API call as fallback.
#     old_primary_api_url = os.getenv('YOUTUBE_API_URL')
#     old_primary_headers = {
#         "x-rapidapi-key": os.getenv('YOUTUBE_API_KEY'),
#         "x-rapidapi-host": os.getenv('YOUTUBE_API_HOST')
#     }
#     try:
#         response = requests.get(old_primary_api_url, headers=old_primary_headers, params=querystring)
#         response.raise_for_status()
#         resp_json = response.json()
#         if resp_json.get("success"):
#             download_link = resp_json.get("download")
#             if download_link:
#                 print(download_link, "download_link from fallback (old primary API)")
#                 return {"download_url": download_link}
#             else:
#                 raise Exception("Download link not found in old primary API response.")
#         else:
#             raise Exception("Old primary API response was not successful.")
#     except Exception as old_primary_error:
#         raise HTTPException(
#             status_code=500,
#             detail=f"Both APIs failed. New primary error: {new_primary_error}; Old primary error: {old_primary_error}"
#         )


# < ========================================================================================================================================================== >

#  MP3 Downloader from YouTube

# def download_youtube_audio(youtube_url: str):
#     # Primary API endpoint and headers (assumed to be set in your environment)
#     primary_api_url = os.getenv('YOUTUBE_API_URL')
#     primary_headers = {
#         "x-rapidapi-key": os.getenv('YOUTUBE_API_KEY'),
#         "x-rapidapi-host": os.getenv('YOUTUBE_API_HOST')
#     }
#     querystring = {"url": youtube_url}
    
#     print(f"[Primary] Requesting MP3 link via RapidAPI for {youtube_url} ...")
    
#     attempts = 15
#     for attempt in range(attempts):
#         try:
#             response = requests.get(primary_api_url, headers=primary_headers, params=querystring)
#             response.raise_for_status()
#             resp_json = response.json()
#             if resp_json.get("success"):
#                 download_link = resp_json.get("download")
#                 if download_link:
#                     print(download_link, "download_link from primary API")
#                     return {"download_url": download_link}
#                 else:
#                     raise Exception("Download link not found in primary API response.")
#             else:
#                 raise Exception("Primary API response was not successful.")
#         except Exception as e:
#             if attempt == attempts - 1:
#                 print("Primary API failed after multiple attempts, trying fallback API.")
#                 # Fallback API endpoint and headers
#                 fallback_api_url = "https://mp3-downloader-from-youtube1.p.rapidapi.com/mp3"
#                 # It’s a good idea to store your fallback key as an environment variable.
#                 fallback_headers = {
#                     "x-rapidapi-key": os.getenv('YOUTUBE_FALLBACK_API_KEY', "3a58ddb767msh7d84042c8432a96p17a624jsn0b27a4e95944"),
#                     "x-rapidapi-host": "mp3-downloader-from-youtube1.p.rapidapi.com"
#                 }
#                 fallback_response = requests.get(fallback_api_url, headers=fallback_headers, params=querystring)
#                 fallback_response.raise_for_status()
#                 fallback_json = fallback_response.json()
#                 if fallback_json.get("success"):
#                     download_link = fallback_json.get("download")
#                     if download_link:
#                         print(download_link, "download_link from fallback API")
#                         return {"download_url": download_link}
#                     else:
#                         raise HTTPException(status_code=500, detail="Download link not found in fallback API response.")
#                 else:
#                     raise HTTPException(status_code=500, detail="Fallback API response was not successful.")
#             else:
#                 print(f"Error on primary attempt {attempt+1}: {e}. Retrying in 5s...")
#                 time.sleep(5)

# < ========================================================================================================================================================== >