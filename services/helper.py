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
import requests
from fastapi import UploadFile, File, HTTPException
import os

async def transcribe_audio(file_path: str):
    try:
        # Ensure the file path exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=400, detail="File not found")

        # Get the domain URL from environment variables
        domain_url = os.getenv('DOMAIN_URL')
        if not domain_url:
            raise HTTPException(status_code=500, detail="DOMAIN_URL is not set")

        # Define the upload endpoint
        upload_endpoint = f"{domain_url}/upload"

        # Open and read the file content
        with open(file_path, "rb") as file:
            files = {
                "file": (os.path.basename(file_path), file, "audio/ogg")  # Adjust MIME type as needed
            }

            # Send the file to the server using a POST request
            response = requests.post(upload_endpoint, files=files)

        # Check for errors in the server response
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"File upload failed: {response.text}")

        # Get the uploaded file's URL from the response
        file_url = response.json().get("file_url")
        if not file_url:
            raise HTTPException(status_code=500, detail="File URL not returned by server")

        # Call the transcription function with the file URL
        transcription_result = get_transcription(file_url)
        return transcription_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

import os
from yt_dlp import YoutubeDL

import os
from yt_dlp import YoutubeDL

def download_youtube_audio(youtube_url: str, output_path: str):
    """
    Downloads audio from a YouTube video and saves it in the specified path.

    :param youtube_url: The YouTube video URL.
    :param output_path: The full path (including filename) where the audio will be saved.
    :return: The output path of the downloaded audio file.
    """
    try:
        # Ensure the directory for the output path exists
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)

        # yt-dlp requires the output template for managing dynamic extensions
        output_template = os.path.splitext(output_path)[0] + ".%(ext)s"

        # yt-dlp options
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
                'preferredquality': '96',
            }],
            'outtmpl': output_template,  # Use template for dynamic extensions
            'quiet': False,  # Suppress logs for production
        }

        # Download and process the audio
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)

        # Determine the final file path (should match .opus extension)
        downloaded_file = os.path.splitext(output_template)[0] + ".opus"

        # Check if the .opus file exists
        if not os.path.exists(downloaded_file):
            raise Exception("Audio file not found after download and postprocessing.")

        # Rename the file to match the desired output path, if needed
        if downloaded_file != output_path:
            os.rename(downloaded_file, output_path)

        return output_path

    except Exception as e:
        raise Exception(f"Failed to download audio: {str(e)}")





# def download_youtube_audio(youtube_url: str, output_path: str) -> str:
#     import yt_dlp
#     import os

#     ydl_opts = {
#         'format': 'bestaudio/best',
#         'outtmpl': output_path,
#         'postprocessors': [{
#             'key': 'FFmpegExtractAudio',
#             'preferredcodec': 'opus',  # Use Opus codec for better compression
#             'preferredquality': '96',  # Bitrate in kbps (adjust as needed)
#         }],
#         'quiet':False,
#         'verbose':True,
#         'cookiefile': 'cookies.txt',
#         'headers': {
#     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
# }
#     }

#     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#         ydl.download([youtube_url])

#     # Ensure the correct extension is used for Opus files
#     opus_file = output_path + ".opus"
#     if os.path.exists(opus_file):
#         return opus_file
#     elif os.path.exists(output_path):
#         return output_path
#     else:
#         raise RuntimeError(f"Downloaded file not found at: {output_path}")
    
    
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




    
    
