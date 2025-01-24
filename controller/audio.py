import os
import shutil
import asyncio
import subprocess
from fastapi import UploadFile, HTTPException
from fastapi.responses import JSONResponse

from services.helper import transcribe_audio


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def transcribe_audio_file(file: UploadFile):
    try:
        temp_file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Convert audio to Opus format for smaller size
        if not file.filename.endswith(".opus"):
            audio_path = os.path.splitext(temp_file_path)[0] + ".opus"
            subprocess.run([
                "ffmpeg", "-i", temp_file_path, 
                "-vn",                          # No video
                "-acodec", "libopus",           # Use Opus codec for better compression
                "-b:a", "96k",                  # Set audio bitrate to 96 kbps
                "-y",                           # Overwrite output file if it exists
                audio_path
            ], check=True)
            os.remove(temp_file_path)
        else:
            audio_path = temp_file_path

        # Transcribe the smaller audio file
        transcription_result = await asyncio.to_thread(transcribe_audio, audio_path)
        os.remove(audio_path)

        return JSONResponse(content=transcription_result, status_code=200)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
