
from fastapi import HTTPException

from services.error_logging import raise_http_exception_once
from services.helper import handle_audio_download_and_transcribe
from services.youtube_helper import (
    get_video_metadata,
    download_youtube_audio,
    send_webhook_status
)

async def transcribe_youtube_video(youtube_url: str,task_id=None, pre_fetched_transcripts=None ):
    """
    Two flows only:
      1) If pre_fetched_transcripts is given => use them (captions available).
      2) If None => fallback => download audio & transcribe (captionless).
    """
    try:
        
        # Get video metadata
        video_metadata = get_video_metadata(youtube_url)

        # A) CAPTIONS AVAILABLE
        if pre_fetched_transcripts is not None:
            print("Captions available, returning transcript directly.")
            return {
                "is_transcript": True,
                "title": video_metadata.get("title"),
                "thumbnail": video_metadata.get("thumbnail"),
                "video_duration": video_metadata.get("video_duration"),
                "data": {
                    "is_runpod": False,   # Since we didn't do fallback
                    "all_transcripts": pre_fetched_transcripts,
                    "status_code": 200
                }
            }
        # B) CAPTIONLESS   
        # Step 1) Analyzing
            
        try:
            result={
                 "title": video_metadata.get("title"),
                "thumbnail": video_metadata.get("thumbnail"),
                "video_duration": video_metadata.get("video_duration"),
            }
            print("Analyzing video...")
            send_webhook_status(task_id, "Analyzing Video","event.analyzing_video",True,result)    

            if video_metadata.get("duration_seconds", 0) > 7200:
                raise HTTPException(
                    status_code=400,
                    detail="Only videos shorter than 2 hours are supported. Please upload a shorter video."
                )
        except Exception as e:
            # If error in analyzing => same event, success=False
            send_webhook_status(task_id, f"Analyzing Video Failed - {str(e)}", "event.analyzing_video", False)
            raise        

        # Step 2) Extracting Audio

        try:
            print("Extracting audio...")
            send_webhook_status(task_id, "Extracting Audio", "event.extracting_audio", True)
            dl_info = download_youtube_audio(youtube_url)
        except Exception as e:
            send_webhook_status(task_id, f"Extracting Audio Failed - {str(e)}", "event.extracting_audio", False)
            raise
        
        dl_url = dl_info.get("download_url")
        local_file_path = dl_info.get("local_path")
        print(f"Downloaded Audio Info: {dl_info}")

        if not dl_url or not local_file_path:
            raise HTTPException(status_code=500, detail="Failed to retrieve fallback audio link.")

        # 2) Transcribe audio
        print(f"Starting transcription for {local_file_path}...")
        transcription_result = await handle_audio_download_and_transcribe(local_file_path, dl_url, task_id, 1200)

        if not transcription_result:
            raise HTTPException(status_code=500, detail="Transcription failed or returned empty response.")

        transcription_result.update(video_metadata)

        print(f"Transcription completed: {transcription_result}")
        return {
            "is_transcript": False,
            "title": video_metadata.get("title"),
            "thumbnail": video_metadata.get("thumbnail"),
            "video_duration": video_metadata.get("video_duration"),
            "data": transcription_result
        }

    except Exception as e:
        print(f"Error in transcribe_youtube_video: {str(e)}")
        raise_http_exception_once(
            e,
            500,
            f"An error occurred: {str(e)}",
            f"The error: {str(e)}, in transcribe_youtube_video in youtube.py"
        )
