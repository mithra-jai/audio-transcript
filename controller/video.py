import os
import shutil
import asyncio
import subprocess
from fastapi import UploadFile, HTTPException
from fastapi.responses import JSONResponse

from services.helper import transcribe_audio

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def transcribe_video_file(file: UploadFile):
    try:
        temp_file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Extract audio quickly and efficiently
        audio_path = os.path.splitext(temp_file_path)[0] + ".opus"
        
        print("Starting FFmpeg process")

        # Use stream copy if audio codec is already compatible
        result = subprocess.run([
            "ffmpeg", "-i", temp_file_path, 
            "-vn",                          # No video
            "-c:a", "libopus",              # Use Opus codec for compression
            "-b:a", "96k",                  # Set bitrate to 96 kbps
            "-y",                           # Overwrite output file
            audio_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        print("FFmpeg process completed")

        os.remove(temp_file_path)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {result.stderr}")

        # Transcribe the audio file
        transcription_result = transcribe_audio(audio_path)
        os.remove(audio_path)

        return transcription_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
