### youtube.py ###
import asyncio
import os
from fastapi.responses import JSONResponse
from fastapi import HTTPException

from services.helper import download_youtube_audio, upload_audio


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def transcribe_youtube_video(youtube_url: str):
    try:
        output_path = os.path.join(UPLOAD_DIR, "youtube_audio.opus")
        output_path = download_youtube_audio(youtube_url, output_path)

        # transcription_result = await asyncio.to_thread(transcribe_audio, output_path)
        transcription_result = await  upload_audio(output_path)
        os.remove(output_path)

        return transcription_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
