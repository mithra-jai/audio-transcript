import os
from fastapi import HTTPException

from services.helper import  safe_remove, single_pass_chunk_and_transcribe
from services.error_logging import raise_http_exception_once

async def transcribe_audio_file(file_path: str):
    try:
        transcription_result = await single_pass_chunk_and_transcribe(file_path, chunk_size=1200)
        return {
            "status_code": 200,
            "data": transcription_result
        }
    except Exception as e:
        raise_http_exception_once(
            e,
            500,
            f"An error occurred: {str(e)}",
            f"The error: {str(e)}, in transcribe_audio_file in audio.py"
        )
    finally:
        safe_remove(file_path)

