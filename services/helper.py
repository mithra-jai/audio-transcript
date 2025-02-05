
import os
from fastapi import FastAPI, File, UploadFile, HTTPException, Header
import time
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
from yt_dlp import YoutubeDL
import requests
import json


# Load environment variables
load_dotenv()



async def upload_audio(file_path: str):
    try:
        # Ensure the file path exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=400, detail="File not found")

        # Get the domain URL from environment variables
        domain_url = os.getenv('DOMAIN_URL')
        
        if not domain_url:
            raise HTTPException(status_code=500, detail="DOMAIN_URL is not set")

        # Define the upload endpoint
        upload_endpoint = f"{domain_url}/{file_path}"
       
        print("UPLOADING STARTED", upload_endpoint)

        # Call the transcription function with the file URL
        transcription_result = get_transcription(upload_endpoint)
        return transcription_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")



def get_transcription(audio_url):
    """
    Transcribe audio from the given URL and extract start, end, and text fields from the result.
    
    Parameters:
        audio_url (str): The URL of the audio file to be transcribed.
        
    Returns:
        list: A list of dictionaries containing start, end, and text fields for each segment.
    
    Raises:
        RuntimeError: If there's an issue initiating or completing the transcription job.
        ValueError: If the response from the server does not contain expected data.
    """
    endpoint_url = os.getenv('RUNPOD_SERVERLESS_URL')
    runpod_api_key = os.getenv('RUNPOD_AUTH_TOKEN')
    
    if not endpoint_url or not runpod_api_key:
        raise ValueError("Endpoint URL or RunPod API key not found in environment variables.")
    
    headers = {
        'authorization': runpod_api_key,
        'content-type': 'application/json',
    }

    payload = json.dumps({
        "input": {
            "audio": audio_url,
        }
    })

    # 1. Initiate the transcription job
    try:
        response = requests.request(
            "POST",
            f"{endpoint_url}/run",
            headers=headers,
            data=payload
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to initiate transcription job: {e}")

    # Parse job initiation response
    try:
        data = response.json()
    except ValueError as e:
        raise RuntimeError(f"Failed to parse initiation response as JSON: {e}")
    
    if "id" not in data:
        raise ValueError("Response JSON does not contain 'id' field - cannot track job.")

    job_id = data["id"]
    job_finished = False
    result = None

    # 2. Poll the status endpoint until the job is completed
    while not job_finished:
        time.sleep(1)
        try:
            status_response = requests.request(
                "GET", 
                f"{endpoint_url}/status/{job_id}",
                headers=headers
            )
            status_response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error while polling job status: {e}")

        try:
            result = status_response.json()
        except ValueError as e:
            raise RuntimeError(f"Failed to parse status response as JSON: {e}")
        
        # Check if the job failed on the server side
        if result.get("status") == "FAILED":
            raise RuntimeError("Transcription job failed on the server side.")
        
        # If completed, exit the loop
        job_finished = (result.get("status") == "COMPLETED")

    # 3. Extract transcription data once job is completed
    if "output" not in result or "segments" not in result["output"]:
        raise ValueError("Transcription result does not contain expected 'segments' field.")

    transcription_result = result["output"]["segments"]
    extracted_data = [
        {
            "text": segment["text"],
            "start": segment["start"],
            "end": segment["end"]
        }
        for segment in transcription_result
    ]

    return {
        "transcript": extracted_data,
        "is_runpod": True
    }



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




    
    
