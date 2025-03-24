import asyncio
import os
import requests
import uuid
import subprocess
from fastapi import HTTPException
from services.helper import handle_audio_download_and_transcribe
from services.youtube_helper import download_youtube_audio, get_all_transcripts_with_fallback, get_video_metadata
from services.error_logging import raise_http_exception_once

async def transcribe_youtube_video(youtube_url: str, is_runpod: bool = False):
    try:
        # Get video metadata including title, thumbnail, video_duration and duration_seconds
        video_metadata = get_video_metadata(youtube_url)

        if is_runpod:
            # Check if video duration is less than 2 hours
            if video_metadata.get("duration_seconds", 0) > 7200:
                raise HTTPException(
                    status_code=400, 
                    detail="Only videos shorter than 2 hours are supported. Please upload a shorter video."
                )
            data = download_youtube_audio(youtube_url)
            url = data.get("download_url")
            local_path = data.get("local_path")
            if not url:
                raise HTTPException(
                    status_code=400, 
                    detail="Failed to retrieve MP3 link for RunPod."
                )
            transcription_result = await handle_audio_download_and_transcribe(local_path, url, 1200)
            transcription_result.update(video_metadata)
            # Unified output structure for runpod branch (if needed you can wrap it inside "data")
            return {
                "is_transcript": False,
                "title": video_metadata.get("title"),
                "thumbnail": video_metadata.get("thumbnail"),
                "video_duration": video_metadata.get("video_duration"),
                "data": transcription_result
            }

        # Get transcripts or fallback data
        data = get_all_transcripts_with_fallback(youtube_url)
        if data.get("is_transcript"):
            # When captions are available, wrap the transcript data into a "data" field.
            result_data = {
                "is_transcript": True,
                "title": video_metadata.get("title"),
                "thumbnail": video_metadata.get("thumbnail"),
                "video_duration": video_metadata.get("video_duration"),
                "data": {
                    "is_runpod": data.get("is_runpod"),
                    "all_transcripts": data.get("all_transcripts"),
                    "status_code": data.get("status_code")
                }
            }
            return result_data
        else:
            # Fallback branch: use runpod transcription
            url = data.get("url")
            local_file_path = data.get("local_path")
            if not url:
                raise HTTPException(
                    status_code=500, 
                    detail="Failed to retrieve fallback audio link."
                )
            if video_metadata.get("duration_seconds", 0) > 7200:
                raise HTTPException(
                    status_code=400, 
                    detail="Only videos shorter than 2 hours are supported. Please upload a shorter video."
                )
            transcription_result = await handle_audio_download_and_transcribe(local_file_path, url, 1200)
            transcription_result.update(video_metadata)
            result_data = {
                "is_transcript": False,
                "title": video_metadata.get("title"),
                "thumbnail": video_metadata.get("thumbnail"),
                "video_duration": video_metadata.get("video_duration"),
                "data": transcription_result
            }
            return result_data

    except Exception as e:
        raise_http_exception_once(
            e,
            500,
            f"An error occurred: {str(e)}",
            f"The error: {str(e)}, in transcribe_youtube_video in youtube.py"
        )

