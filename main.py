import os
import time
from fastapi import FastAPI, UploadFile, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from services.helper import check_api_key, save_upload_file
from tasks import process_audio_task, process_video_task, process_youtube_task
from celeryapp import celery
from celery.result import AsyncResult
from services.error_logging import log_error_once, raise_http_exception_once

load_dotenv()
app = FastAPI()

# Custom exception handler to return errors with a status_code and data field.
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
         status_code=exc.status_code,
         content={
              "status_code": exc.status_code,
              "data": {"detail": exc.detail}
         }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

class YouTubeRequest(BaseModel):
    youtube_url: str
    is_runpod: bool = False

@app.post("/transcribe_audio")
async def transcribe_audio_endpoint(file: UploadFile, api_key: str = Header(None)):
    if not api_key or not check_api_key(api_key):
        raise_http_exception_once(
            Exception("API Key mismatch"),
            403,
            "Unauthorized",
            "The error: Unauthorized API key, in transcribe_audio_endpoint in main.py"
        )
    # Ensure the file is an audio file (this was added in your previous update)
    if not file.content_type.startswith("audio/"):
        raise_http_exception_once(
            Exception("Invalid file type"),
            400,
            "Invalid file type: Expected audio file",
            f"Error: Received file with content_type {file.content_type} in transcribe_audio_endpoint in main.py"
        )

    start_time = time.time()
    file_path = save_upload_file(file)
    file_saved_time = time.time()

    main_upload_time = file_saved_time - start_time
    job = process_audio_task.delay(file_path, start_time, main_upload_time)
    return {"status_code": 200, "task_id": job.id, "status": "queued"}

@app.post("/transcribe_video")
async def transcribe_video_endpoint(file: UploadFile, api_key: str = Header(None)):
    if not api_key or not check_api_key(api_key):
        raise_http_exception_once(
            Exception("API Key mismatch"),
            403,
            "Unauthorized",
            "The error: Unauthorized API key, in transcribe_video_endpoint in main.py"
        )
    # Ensure the file is a video file
    if not file.content_type.startswith("video/"):
        raise_http_exception_once(
            Exception("Invalid file type"),
            400,
            "Invalid file type: Expected video file",
            f"Error: Received file with content_type {file.content_type} in transcribe_video_endpoint in main.py"
        )

    start_time = time.time()
    file_path = save_upload_file(file)
    file_saved_time = time.time()

    main_upload_time = file_saved_time - start_time
    job = process_video_task.delay(file_path, start_time, main_upload_time)
    return {"status_code": 200, "task_id": job.id, "status": "queued"}

@app.post("/transcribe_youtube")
async def transcribe_youtube_endpoint(request: YouTubeRequest, api_key: str = Header(None)):
    if not api_key or not check_api_key(api_key):
        raise_http_exception_once(
            Exception("API Key mismatch"),
            403,
            "Unauthorized",
            "The error: Unauthorized API key, in transcribe_youtube_endpoint in main.py"
        )

    start_time = time.time()
    job = process_youtube_task.delay(request.youtube_url, request.is_runpod, start_time)
    return {"status_code": 200, "task_id": job.id, "status": "queued"}

@app.get("/task_status/{task_id}")
def get_task_status(task_id: str, api_key: str = Header(None)):
    if not api_key or not check_api_key(api_key):
        raise_http_exception_once(
            Exception("API Key mismatch"),
            403,
            "Unauthorized",
            "The error: Unauthorized API key, in get_task_status in main.py"
        )
    res = AsyncResult(task_id, app=celery)
    if res.ready():
        return {
            "status_code": 200,
            "task_id": task_id,
            "status": "completed",
            "result": res.result
        }
    else:
        return {"status_code": 200, "task_id": task_id, "status": res.state}

@app.get("/")
def read_root():
    return {"status_code": 200, "message": "Welcome to the Whisper Transcription API"}
