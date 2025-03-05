import asyncio
import time
from celeryapp import celery
from fastapi import HTTPException
from controller.audio import transcribe_audio_file
from controller.video import transcribe_video_file
from controller.youtube import transcribe_youtube_video
from services.error_logging import log_error_once

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
def process_youtube_task(youtube_url: str, is_runpod: bool, start_time: float) -> dict:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        tstart = time.time()
        result = loop.run_until_complete(transcribe_youtube_video(youtube_url, is_runpod))
        tend = time.time()

        if "data" not in result:
            new_data = {}
            for k in ("is_runpod", "all_transcripts", "transcript", "status_code"):
                if k in result:
                    new_data[k] = result.pop(k)
            result["data"] = new_data

        data_dict = result["data"]
        transcription_time = tend - tstart
        total_time = tend - start_time

        data_dict["upload_time"] = 0
        data_dict["transcription_time"] = transcription_time
        data_dict["total_time"] = total_time

        result["status_code"] = 200
        return result

    except HTTPException as e:
        log_error_once(e, f"The error: {e.detail}, in process_youtube_task in tasks.py")
        return {
            "status_code": e.status_code,
            "data": {
                "detail": f"HTTPException: {e.detail}"
            }
        }
    except Exception as gen_err:
        log_error_once(gen_err, f"The error: {str(gen_err)}, in process_youtube_task in tasks.py")
        return {
            "status_code": 500,
            "data": {
                "detail": f"Unhandled exception: {str(gen_err)}"
            }
        }
