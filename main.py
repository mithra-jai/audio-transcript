
## main.py ###
import os
import shutil
import asyncio
from fastapi import FastAPI, UploadFile, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from controller.audio import transcribe_audio_file
from controller.video import transcribe_video_file
from controller.youtube import transcribe_youtube_video
from services.helper import check_api_key


# Load environment variables
load_dotenv()

app = FastAPI()
origins = ["*"] 
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app = FastAPI()

class YouTubeRequest(BaseModel):
    youtube_url: str

@app.post("/transcribe_audio")
async def transcribe_audio_endpoint(file: UploadFile, api_key: str = Header(...)):
    if not check_api_key(api_key):
        raise HTTPException(status_code=403, detail="The user is unauthorized")
    return await transcribe_audio_file(file)

@app.post("/transcribe_youtube")
async def transcribe_youtube_endpoint(request: YouTubeRequest, api_key: str = Header(...)):
    if not check_api_key(api_key):
        raise HTTPException(status_code=403, detail="The user is unauthorized")
    return await transcribe_youtube_video(request.youtube_url)

@app.post("/transcribe_video")
async def transcribe_video_endpoint(file: UploadFile, api_key: str = Header(...)):
    if not check_api_key(api_key):
        raise HTTPException(status_code=403, detail="The user is unauthorized")
    return await transcribe_video_file(file)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Whisper Transcription API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)