import os
import shutil
import requests
import asyncio
import subprocess
import time
from dotenv import load_dotenv
load_dotenv()
from fastapi import UploadFile, HTTPException
from fastapi.responses import JSONResponse

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled
)
from urllib.parse import urlparse, parse_qs
import json


proxy_username= os.getenv('PROXY_USER')
proxy_password= os.getenv('PROXY_PASSWORD')
proxy_port=os.getenv('PROXY_PORT')

proxies = {
        "http": f"http://{proxy_username}:{proxy_password}@gate.smartproxy.com:{proxy_port}",
        "https":f"https://{proxy_username}:{proxy_password}@gate.smartproxy.com:{proxy_port}"
    }



def extract_video_id(url: str) -> str:
    """
    Extracts the video ID from a YouTube URL.
    Handles:
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
    """
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    path = parsed_url.path

    # 1) youtu.be
    if 'youtu.be' in domain:
        video_id = path.lstrip('/')
        if not video_id:
            raise ValueError("No video ID found in youtu.be URL.")
        return video_id

    # 2) youtube.com
    if 'youtube.com' in domain:
        # 2a) Shorts
        if path.startswith('/shorts/'):
            segments = path.split('/')
            if len(segments) >= 3 and segments[1] == 'shorts':
                video_id = segments[2]
                if video_id:
                    return video_id
                else:
                    raise ValueError("No video ID found in shorts path.")
            else:
                raise ValueError("Unexpected path format for YouTube Shorts URL.")
        
        # 2b) Normal watch link
        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            return query_params['v'][0]
        
        raise ValueError("No video ID found in youtube.com URL parameters.")
    
    raise ValueError("Not a valid YouTube URL.")

def convert_to_start_end_format(transcript_list):
    """
    Converts each transcript entry from {text, start, duration}
    into {text, start, end}.
    """
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
    """
    Returns ALL transcripts for the given YouTube video URL,
    in {text, start, end} format for each segment.
    """
    video_id = extract_video_id(url)
    try:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    except NoTranscriptFound:
        raise NoTranscriptFound(f"No transcripts found for video ID '{video_id}'")
    except TranscriptsDisabled:
        raise TranscriptsDisabled(f"Transcripts are disabled for video ID '{video_id}'")

    all_transcripts = []
    for t in transcripts:
        raw_data = t.fetch()
        converted_data = convert_to_start_end_format(raw_data)
        all_transcripts.append({
            "language": t.language,
            "language_code": t.language_code,
            "is_generated": t.is_generated,
            "is_translatable": t.is_translatable,
            "translation_languages": t.translation_languages,
            "transcript": converted_data
        })
    return all_transcripts

def get_english_transcript(url: str):
    """
    Returns the English transcript (in start/end format) if it exists.
    Priority:
      1) Manually created English
      2) Auto-generated English
      3) Translated from any other language to English
      4) Raises NoTranscriptFound if none is available
    """
    video_id = extract_video_id(url)
    try:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    except NoTranscriptFound:
        raise NoTranscriptFound(f"No transcripts found for video ID '{video_id}'")
    except TranscriptsDisabled:
        raise TranscriptsDisabled(f"Transcripts are disabled for video ID '{video_id}'")

    # 1) Manually created English transcript
    try:
        manual_en = transcripts.find_manually_created_transcript(['en'])
        return convert_to_start_end_format(manual_en.fetch())
    except NoTranscriptFound:
        pass

    # 2) Auto-generated English transcript
    try:
        auto_en = transcripts.find_generated_transcript(['en'])
        return convert_to_start_end_format(auto_en.fetch())
    except NoTranscriptFound:
        pass

    # 3) Translate from any transcript
    for t in transcripts:
        if t.is_translatable:
            try:
                return convert_to_start_end_format(t.translate('en').fetch())
            except:
                pass

    # 4) If no English transcript found/translatable
    raise NoTranscriptFound("No English transcript (or translation) available.")

# --------------------------------------------------------------------------
# Fallback to audio if no official transcripts are found
# --------------------------------------------------------------------------
def download_youtube_audio(youtube_url: str):
    """
    1) Call the RapidAPI endpoint to begin/continue converting to MP3.
    2) Return the download link if successful.
    """
    api_url = os.getenv('YOUTUBE_API_URL')
    querystring = {"url": youtube_url}
    headers = {
        "x-rapidapi-key": os.getenv('YOUTUBE_API_KEY'),
        "x-rapidapi-host": os.getenv('YOUTUBE_API_HOST')
    }

    print(f"[Fallback] Requesting MP3 link via RapidAPI for {youtube_url} ...")

    try:
        response = requests.get(api_url, headers=headers, params=querystring)
        response.raise_for_status()
        resp_json = response.json()

        # Check if "success" is True and return the download link
        if resp_json.get("success"):
            download_link = resp_json.get("download")
            if download_link:
                print(download_link,"download_link====================================================")
                return {"download_url": download_link}
            else:
                raise HTTPException(status_code=500, detail="Download link not found in response.")
        else:
            print("Success value: ",resp_json.get("success"))
            raise HTTPException(status_code=500, detail="API response was not successful.")

    except Exception as e:
        print("ERROR for download API: ", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve MP3 link: {str(e)}")


def get_all_transcripts_and_english(url: str):
    """
    Tries to get all transcripts + the English transcript from YouTube. 
    If none are found, fallback returns a download link.
    """
    video_id = extract_video_id(url)

    try:
        # Attempt to fetch all transcripts
        all_t = get_all_transcripts(url)
        # First, check if we already have an English transcript in 'all_t'
        en_t = None
        for transcript_data in all_t:
            if transcript_data["language_code"] == "en":
                en_t = transcript_data["transcript"]
                break  # Found an English transcript; no need to look further

        # If no English transcript was found in 'all_t', try to get it
        if en_t is None:
            try:
                en_t = get_english_transcript(url)
            except NoTranscriptFound:
                en_t = None  # No English transcript specifically

        return {
            "is_runpod":False,
            "is_transcript": True,
            "all_transcripts": all_t,
            "english_transcript": en_t
        }
    
    except (NoTranscriptFound, TranscriptsDisabled, ValueError, Exception) as e:
        # Log the error and fallback to downloading audio
        print(f"[Fallback] Transcript retrieval failed ({str(e)}). Downloading audio...")

        try:
            fallback_result = download_youtube_audio(url)
            download_url = fallback_result.get("download_url", "")

            return {
                "is_transcript": False,
                "url": download_url
            }

        except Exception as audio_error:
            print(f"[Error] Audio download also failed: {str(audio_error)}")
            raise HTTPException(status_code=500, detail="Failed to retrieve transcript or download audio.")




