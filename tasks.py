import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
import time
from celeryapp import celery
from fastapi import HTTPException
from controller.audio import transcribe_audio_file
from controller.video import transcribe_video_file
from controller.youtube import transcribe_youtube_video
from services.error_logging import log_error_once
from services.youtube_helper import (
    get_all_transcripts, is_valid_youtube_url, send_webhook_status,
    NoTranscriptFound,
    TranscriptsDisabled
)
@celery.task
def process_audio_task(file_path: str, start_time: float, main_upload_time: float) -> dict:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(transcribe_audio_file(file_path))
        data_dict = result.get("data", {})
        if not isinstance(data_dict, dict):
            data_dict = {}

        chunk_time = data_dict.pop("chunk_time", 0.0)
        transcription_time = data_dict.pop("transcription_time", 0.0)

        upload_time = main_upload_time + chunk_time
        now = time.time()
        total_time = now - start_time

        data_dict["upload_time"] = upload_time
        data_dict["transcription_time"] = transcription_time
        data_dict["total_time"] = total_time
        result["data"] = data_dict

        return result

    except HTTPException as e:
        # Only log if this is not already reported
        log_error_once(e, f"The error: {e.detail}, in process_audio_task in tasks.py")
        return {
            "status_code": e.status_code,
            "data": {
                "detail": f"HTTPException occurred: {e.detail}"
            }
        }
    except Exception as gen_err:
        log_error_once(gen_err, f"The error: {str(gen_err)}, in process_audio_task in tasks.py")
        return {
            "status_code": 500,
            "data": {
                "detail": f"Unhandled exception: {str(gen_err)}"
            }
        }

@celery.task
def process_video_task(file_path: str, start_time: float, main_upload_time: float) -> dict:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(transcribe_video_file(file_path))
        data_dict = result.get("data", {})
        if not isinstance(data_dict, dict):
            data_dict = {}

        chunk_time = data_dict.pop("chunk_time", 0.0)
        transcription_time = data_dict.pop("transcription_time", 0.0)

        upload_time = main_upload_time + chunk_time
        total_time = time.time() - start_time

        data_dict["upload_time"] = upload_time
        data_dict["transcription_time"] = transcription_time
        data_dict["total_time"] = total_time

        result["data"] = data_dict
        return result

    except HTTPException as e:
        log_error_once(e, f"The error: {e.detail}, in process_video_task in tasks.py")
        return {
            "status_code": e.status_code,
            "data": {
                "detail": f"HTTPException: {e.detail}"
            }
        }
    except Exception as gen_err:
        log_error_once(gen_err, f"The error: {str(gen_err)}, in process_video_task in tasks.py")
        return {
            "status_code": 500,
            "data": {
                "detail": f"Unhandled exception: {str(gen_err)}"
            }
        }

@celery.task
def process_youtube_task(youtube_url: str, start_time: float) -> dict:
    """
    1) We try calling get_all_transcripts once to see if captions are available.
    2) If they exist => do synchronous route with force_fallback=False.
    3) If they fail => do queued fallback route with force_fallback=True.
    """
    webhook_url = os.getenv('WEBHOOK_URL')
    current_task_id = process_youtube_task.request.id
    # 1) Validate YouTube URL
    if not is_valid_youtube_url(youtube_url):
        # Instead of raising HTTPException, return a dict
        return {
            "task_id": current_task_id,
            "status": "Invalid YouTube URL. Please provide a valid video or Shorts link.",
            "result": None,
            "status_code": 400
        }

    # Try exactly once
    transcripts = None
    caption_available = False
    try:
        transcripts = get_all_transcripts(youtube_url)
        caption_available = True
    except (NoTranscriptFound, TranscriptsDisabled, HTTPException):
        # Treat any of these as "no captions"
        caption_available = False
    except Exception:
        # Catch-all for unexpected errors so we still do fallback
        caption_available = False    

    if caption_available and transcripts:

        # Caption branch: process synchronously.

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tstart = time.time()
        result = loop.run_until_complete(
            transcribe_youtube_video(
                youtube_url, current_task_id,
                pre_fetched_transcripts=transcripts  # We already have captions
            )
        )
        tend = time.time()
        
        if "data" in result:
            result["data"]["transcription_time"] = tend - tstart
            result["data"]["total_time"] = time.time() - start_time
       
        
        # Return full result so the HTTP endpoint can reply immediately.
        return {
            "task_id": current_task_id,
            "status": "Completed",
            "result":result,
            "status_code": 200
        }
    else:
        # Fallback branch: captions not available.
        # Capture current task id.
        
        process_youtube_fallback_task.delay(youtube_url, start_time, webhook_url, current_task_id)
        # Immediately return minimal response with current task id.
        return {
            "task_id": current_task_id,
            "status": "queued",
            "result": None,
            "status_code": 202
        }


# New helper function to process fallback synchronously
@celery.task
def process_youtube_fallback_task(youtube_url: str, start_time: float, webhook_url: str, task_id: str):
    try:
        send_webhook_status(task_id, "queued", "event.queued", True)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tstart = time.time()
        result = loop.run_until_complete(
            transcribe_youtube_video(youtube_url, task_id)
        )
        tend = time.time()
        
        if "data" in result:
            result["data"]["transcription_time"] = tend - tstart
            result["data"]["total_time"] = time.time() - start_time
        result["status_code"] = 200
        
        if webhook_url:
            
            try:
                print("Audio transcription completed")
                send_webhook_status( task_id, "completed","event.completed", result)
            except Exception as e:
                from services.error_logging import log_error_once
                log_error_once(e, f"Failed to send fallback webhook callback: {str(e)}")
    except Exception as e:
        # error => keep the event that failed, or choose event.fallback_started if it fails right away
      
        raise        

