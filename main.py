import os
import time
from fastapi import FastAPI, UploadFile, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from dotenv import load_dotenv

from services.helper import check_api_key, save_upload_file
from tasks import process_audio_task, process_video_task, process_youtube_task
from celeryapp import celery
from celery.result import AsyncResult
from services.error_logging import log_error_once, raise_http_exception_once

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

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


# Custom exception handler for request validation errors.
@app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    # Return your desired custom error structure.
    return JSONResponse(
        status_code=422,
        content=
        {
            "task_id": None,
            "status": "youtube_url parameter is required",
            "result": None,
            "status_code": 422
        }

    )
class YouTubeRequest(BaseModel):
    youtube_url: str
   

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
    # Validate API key.
    if not api_key or not check_api_key(api_key):
        return {
            "task_id": None,
            "status": "Invalid or missing API key. Access denied",
            "result": None,
            "status_code": 403
        }

    
    # The YouTubeRequest model already ensures 'youtube_url' is present.
    # However, if for any reason it's missing, this check is extra protection.
    if not request.youtube_url:
        return {
            "task_id": None,
            "status": "Missing required parameter",
            "result": None,
            "status_code": 400
        }
    
    start_time = time.time()

    # Queue the task.
    job = process_youtube_task.delay(request.youtube_url, start_time)

    # Wait for the task's quick response.
    task_return = job.get()

    response_status_code = task_return.get("status_code", 500)
    return JSONResponse(
        status_code=response_status_code,
        content={
            "task_id": task_return.get("task_id"),
            "status": task_return.get("status"),
            "result": task_return.get("result"),
            "status_code": response_status_code
        }
    )




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
