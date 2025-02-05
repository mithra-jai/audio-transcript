### youtube.py ###
import asyncio
import os
from fastapi.responses import JSONResponse
from fastapi import HTTPException

from services.helper import  get_transcription
from services.youtube_helper import get_all_transcripts_and_english


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def transcribe_youtube_video(youtube_url: str):
    try:
        data = get_all_transcripts_and_english(youtube_url)
        if data["is_transcript"]:  
           return data
        else:
            url=data['url']
            print("URL to runpod", url, "*****************************************")
            data=get_transcription(url)
            return data

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
