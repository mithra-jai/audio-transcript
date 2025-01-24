import asyncio
import os
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException, Header
import time
from gradio_client import Client, handle_file
from fastapi.responses import JSONResponse
from dotenv import load_dotenv


# Load environment variables
load_dotenv()


UPLOAD_DIR = "uploads"
async def transcribe_audio(file: UploadFile = File(...)):
    # Save the uploaded file to the server
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    
    with open(file_location, "wb") as f:
        shutil.copyfileobj(file.file, f)
    domain_url= os.getenv('DOMAIN_URL')  
    file_url=f"{domain_url}{file.filename}"  
    print("File_url",file_url)
    # Return the URL where the file can be accessed
    return get_transcription(file_url)


def download_youtube_audio(youtube_url: str, output_path: str) -> str:
    import yt_dlp
    import os

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'opus',  # Use Opus codec for better compression
            'preferredquality': '96',  # Bitrate in kbps (adjust as needed)
        }],
        'quiet':False,
        'verbose':True,
        'cookiefile': 'cookies.txt',
        'headers': {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])

    # Ensure the correct extension is used for Opus files
    opus_file = output_path + ".opus"
    if os.path.exists(opus_file):
        return opus_file
    elif os.path.exists(output_path):
        return output_path
    else:
        raise RuntimeError(f"Downloaded file not found at: {output_path}")
    
    
import json
import requests
import time

def get_transcription(audio_url):
    """
    Transcribe audio from the given URL and extract start, end, and text fields from the result.
    
    Parameters:
        audio_url (str): The URL of the audio file to be transcribed.
        
    Returns:
        list: A list of dictionaries containing start, end, and text fields for each segment.
    """
    # Define the API endpoint and headers
    endpoint_url = os.getenv('RUNPOD_SERVERLESS_URL')
    runpod_api_key = os.getenv('RUNPOD_AUTH_TOKEN')
    headers = {
        'authorization': runpod_api_key,  # Replace with your API key
        'content-type': 'application/json',
    }

    # Create the payload for the API request
    payload = json.dumps({
        "input": {
            "audio": audio_url,
        }
    })

    # Send the initial POST request
    response = requests.request("POST", f"{endpoint_url}/run", headers=headers, data=payload)
    data = response.json()

    # Get the job ID
    job_id = data["id"]
    job_finished = False
    result = None

    # Poll the status endpoint until the job is completed
    while not job_finished:
        time.sleep(1)
        response = requests.request("GET", f"{endpoint_url}/status/{job_id}", headers=headers)
        result = response.json()
        job_finished = result["status"] == "COMPLETED"

    # Extract relevant fields from the transcription result
    transcription_result = result['output']['segments']
    extracted_data = [
        {
            "text": segment["text"],
            "start": segment["start"],
            "end": segment["end"]
        }
        for segment in transcription_result
    ]

    return extracted_data


def check_api_key(api_key):
    try:
        actual_api_key = os.getenv('API_KEY')
        if api_key and api_key != actual_api_key:
            return False
        else:
            return True
    except Exception as e:
        print(f"An error occurred while checking for API key: {e}")
        return False   




    
    
