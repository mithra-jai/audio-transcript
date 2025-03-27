import os
import time
import json
import glob
import requests
import subprocess
import asyncio
import uuid
import shutil
from fastapi import UploadFile
from dotenv import load_dotenv
from services.youtube_helper import send_webhook_status
from services.error_logging import log_error_once, raise_http_exception_once

load_dotenv()


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def safe_remove(path: str):
    """
    Safely removes a file if it exists.
    """
    if os.path.exists(path):
        os.remove(path)

def save_upload_file(file: UploadFile) -> str:
    temp_file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(temp_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return temp_file_path

def check_api_key(api_key: str) -> bool:
    try:
        actual_api_key = os.getenv('API_KEY')
        if api_key and api_key != actual_api_key:
            return False
        return True
    except Exception as e:
        print(f"An error occurred while checking for API key: {e}")
        log_error_once(e, f"The error: {str(e)}, in check_api_key in helper.py")
        return False

def get_transcription(audio_url: str) -> dict:
    endpoint_url = os.getenv('RUNPOD_SERVERLESS_URL')
    runpod_api_key = os.getenv('RUNPOD_AUTH_TOKEN')
    if not endpoint_url or not runpod_api_key:
        raise_http_exception_once(
            Exception("Missing env keys"),
            500,
            "Endpoint URL or RunPod API key not found in environment variables.",
            "The error: Endpoint URL or RunPod API key not found in environment variables, in get_transcription in helper.py"
        )

    headers = {
        'authorization': runpod_api_key,
        'content-type': 'application/json',
    }

    payload = json.dumps({"input": {"audio": audio_url}})

    # 1) Initiate the transcription job
    try:
        response = requests.post(f"{endpoint_url}/run", headers=headers, data=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise_http_exception_once(
            e,
            500,
            f"Failed to initiate transcription job: {e}",
            f"The error: {str(e)}, in get_transcription in helper.py"
        )

    # 2) Parse job initiation response
    try:
        data = response.json()
    except ValueError as e:
        raise_http_exception_once(
            e,
            500,
            f"Failed to parse initiation response as JSON: {e}",
            f"The error: {str(e)}, in get_transcription in helper.py"
        )

    if "id" not in data:
        raise_http_exception_once(
            Exception("No 'id' in response"),
            500,
            "Response JSON does not contain 'id' field - cannot track job.",
            "The error: Response JSON does not contain 'id' field - cannot track job, in get_transcription in helper.py"
        )

    job_id = data["id"]
    job_finished = False
    result = None

    # 3) Poll the status until "COMPLETED"
    while not job_finished:
        time.sleep(1)
        try:
            status_response = requests.get(f"{endpoint_url}/status/{job_id}", headers=headers)
            status_response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise_http_exception_once(
                e,
                500,
                f"Error while polling job status: {e}",
                f"The error: {str(e)}, in get_transcription in helper.py"
            )

        try:
            result = status_response.json()
        except ValueError as e:
            raise_http_exception_once(
                e,
                500,
                f"Failed to parse status response as JSON: {e}",
                f"The error: {str(e)}, in get_transcription in helper.py"
            )

        if result.get("status") == "FAILED":
            raise_http_exception_once(
                Exception("Job failed on server"),
                500,
                "Transcription job failed on the server side.",
                "The error: Transcription job failed on the server side, in get_transcription in helper.py"
            )

        job_finished = (result.get("status") == "COMPLETED")

    # 4) Extract final segments
    if "output" not in result or "segments" not in result["output"]:
        raise_http_exception_once(
            Exception("Missing 'segments' in response"),
            500,
            "Transcription result does not contain expected 'segments' field.",
            "The error: Transcription result does not contain expected 'segments' field, in get_transcription in helper.py"
        )

    segments = result["output"]["segments"]
    transcript_data = [
        {"text": seg["text"], "start": seg["start"], "end": seg["end"]}
        for seg in segments
    ]
    detected_lang = result["output"].get("detected_language", None)

    return {
        "transcript": transcript_data,
        "detected_language": detected_lang,
        "is_runpod": True,
        "status_code": 200
    }

def build_chunk_url(file_path: str) -> str:
    if not os.path.exists(file_path):
        raise_http_exception_once(
            Exception("Chunk missing"),
            400,
            f"Chunk not found: {file_path}",
            f"The error: Chunk not found: {file_path}, in build_chunk_url in helper.py"
        )

    domain_url = os.getenv('DOMAIN_URL')
    if not domain_url:
        raise_http_exception_once(
            Exception("Missing DOMAIN_URL"),
            500,
            "DOMAIN_URL is not set",
            "The error: DOMAIN_URL is not set, in build_chunk_url in helper.py"
        )

    print(f"{domain_url}/{file_path}","DOMAIN URL")
    return f"{domain_url}/{file_path}"
def single_pass_segment_transcode(input_path: str, segment_time: int = 1200) -> list:
    base, ext = os.path.splitext(input_path)
    chunk_pattern = f"{base}_chunk_%03d{ext}"  # Keep the same format

    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-vn",
        "-acodec", "copy",  # No encoding
        "-f", "segment",
        "-segment_time", str(segment_time),
        "-reset_timestamps", "1",
        chunk_pattern,
        "-y"
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise_http_exception_once(
            e,
            500,
            f"FFmpeg single-pass error: {str(e)}",
            f"The error: FFmpeg single-pass error: {str(e)}, in single_pass_segment_transcode in helper.py"
        )

    chunk_files = glob.glob(f"{base}_chunk_*{ext}")  # Match correct extension
    chunk_files.sort()
    if not chunk_files:
        raise_http_exception_once(
            Exception("No chunk files"),
            500,
            "No chunk files created by FFmpeg.",
            "The error: No chunk files created by FFmpeg, in single_pass_segment_transcode in helper.py"
        )

    return chunk_files

# def single_pass_segment_transcode(input_path: str, segment_time: int = 1200) -> list:
#     base, _ = os.path.splitext(input_path)
#     chunk_pattern = f"{base}_chunk_%03d.aac"

#     cmd = [
#         "ffmpeg",
#         "-i", input_path,
#         "-vn",
#         "-acodec", "copy",
#         "-f", "segment",
#         "-segment_time", str(segment_time),
#         "-reset_timestamps", "1",
#         chunk_pattern,
#         "-y"
#     ]

#     try:
#         subprocess.run(cmd, check=True)
#     except subprocess.CalledProcessError as e:
#         raise_http_exception_once(
#             e,
#             500,
#             f"FFmpeg single-pass error: {str(e)}",
#             f"The error: FFmpeg single-pass error: {str(e)}, in single_pass_segment_transcode in helper.py"
#         )

#     chunk_files = glob.glob(f"{base}_chunk_*.aac")
#     chunk_files.sort()
#     if not chunk_files:
#         raise_http_exception_once(
#             Exception("No chunk files"),
#             500,
#             "No chunk files created by FFmpeg.",
#             "The error: No chunk files created by FFmpeg, in single_pass_segment_transcode in helper.py"
#         )

#     return chunk_files

async def single_pass_chunk_and_transcribe(file_path: str, segment_time: int = 1200) -> dict:
    chunk_start = time.time()
    chunk_files = single_pass_segment_transcode(file_path, segment_time=segment_time)
    chunk_end = time.time()
    chunk_time = chunk_end - chunk_start

    transcription_start = time.time()
    if len(chunk_files) == 1:
        chunk_url = build_chunk_url(chunk_files[0])
        trans_result = get_transcription(chunk_url)
        transcription_end = time.time()
        transcription_time = transcription_end - transcription_start

        return {
            "transcript": trans_result["transcript"],
            "detected_language": trans_result.get("detected_language"),
            "is_runpod": True,
            "status_code": 200,
            "chunk_time": chunk_time,
            "transcription_time": transcription_time
        }

    # multiple chunks => run in parallel
    tasks = []
    for i, chunk_path in enumerate(chunk_files):
        tasks.append(asyncio.to_thread(get_transcription, build_chunk_url(chunk_path)))

    results = await asyncio.gather(*tasks)
    transcription_end = time.time()
    transcription_time = transcription_end - transcription_start

    first_chunk_lang = results[0].get("detected_language")
    merged_segments = []
    for i, rdict in enumerate(results):
        offset = i * segment_time
        for seg in rdict.get("transcript", []):
            seg["start"] += offset
            seg["end"]   += offset
        merged_segments.extend(rdict.get("transcript", []))

    # cleanup
    for cp in chunk_files:
        safe_remove(cp)

    return {
        "transcript": merged_segments,
        "detected_language": first_chunk_lang,
        "is_runpod": True,
        "status_code": 200,
        "chunk_time": chunk_time,
        "transcription_time": transcription_time
    }

def get_audio_duration(file_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        file_path
    ]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
        return float(output)
    except Exception as e:
        raise_http_exception_once(
            e,
            500,
            f"Failed to get duration via ffprobe: {str(e)}",
            f"The error: {str(e)}, in get_audio_duration in helper.py"
        )

def chunk_audio(file_path: str, chunk_size: int = 1200) -> list:
    print("chunk_audio => using file:", file_path)
    base, ext = os.path.splitext(file_path)
    chunk_pattern = f"{base}_chunk_%03d{ext}"

    cmd = [
        "ffmpeg",
        "-i", file_path,
        "-f", "segment",
        "-segment_time", str(chunk_size),
        "-c", "copy",
        chunk_pattern,
        "-y"
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise_http_exception_once(
            e,
            500,
            f"FFmpeg error while chunking: {str(e)}",
            f"The error: {str(e)}, in chunk_audio in helper.py"
        )

    chunk_files = []
    idx = 0
    while True:
        test_path = f"{base}_chunk_{idx:03d}{ext}"
        if os.path.exists(test_path):
            chunk_files.append(test_path)
            idx += 1
        else:
            break

    return chunk_files

async def chunk_and_transcribe(file_path: str, chunk_size: int = 1200) -> dict:
    chunk_start = time.time()
    chunk_paths = chunk_audio(file_path, chunk_size=chunk_size)
    chunk_end = time.time()
    chunk_time = chunk_end - chunk_start

    transcription_start = time.time()
    tasks = []
    for i, cp in enumerate(chunk_paths):
        tasks.append(asyncio.to_thread(get_transcription, build_chunk_url(cp)))
    results = await asyncio.gather(*tasks)
    transcription_end = time.time()
    transcription_time = transcription_end - transcription_start

    detected_lang = results[0].get("detected_language")
    merged_segments = []
    for i, rdict in enumerate(results):
        offset = i * chunk_size
        for seg in rdict.get("transcript", []):
            seg["start"] += offset
            seg["end"]   += offset
        merged_segments.extend(rdict.get("transcript", []))

    # cleanup
    for cp in chunk_paths:
        safe_remove(cp)

    return {
        "transcript": merged_segments,
        "detected_language": detected_lang,
        "is_runpod": True,
        "status_code": 200,
        "chunk_time": chunk_time,
        "transcription_time": transcription_time
    }

def extension_for_codec(codec_name: str) -> str:
    """Return the correct file extension for the given audio codec name."""
    codec_name = codec_name.lower()
    if codec_name == "mp3":
        return ".mp3"
    elif codec_name == "aac":
        return ".aac"
    elif codec_name == "opus":
        return ".opus"
    elif codec_name == "vorbis":
        return ".ogg"
    # fallback
    return f".{codec_name}"

# ---------------------------------------------------------------------
# NEW HELPER #2: ensure_audio_only
# ---------------------------------------------------------------------
def ensure_audio_only(file_path: str) -> str:
    """
    1) ffprobe 'file_path' to see the real codec & check if there's video or multiple audio streams.
    2) If there's exactly one audio stream, no video, but the extension is wrong, rename it.
    3) Otherwise, extract a single audio track (no re-encode, just copy) to a new file with the correct extension.
    4) Return the path to this final audio-only file.
    """
    # 1) Probe the file to see the actual streams
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", file_path
    ]
    try:
        probe_output = subprocess.check_output(probe_cmd)
        probe_data = json.loads(probe_output)
    except Exception as e:
        raise_http_exception_once(
            e,
            500,
            f"Failed to probe file: {file_path}",
            f"The error: {str(e)}, in ensure_audio_only in youtube.py"
        )

    streams = probe_data.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    # 2) If there's exactly 1 audio stream and no video => might just rename it
    if len(video_streams) == 0 and len(audio_streams) == 1:
        audio_codec = audio_streams[0].get("codec_name", "aac").lower()
        correct_ext = extension_for_codec(audio_codec)

        base, current_ext = os.path.splitext(file_path)
        if current_ext.lower() != correct_ext:
            # rename the file on disk
            new_path = base + correct_ext
            os.rename(file_path, new_path)
            return new_path
        else:
            # no rename needed
            return file_path

    # 3) If there's video or multiple audio streams => extract the first audio track only
    if audio_streams:
        audio_codec = audio_streams[0].get("codec_name", "aac").lower()
    else:
        audio_codec = "aac"

    correct_ext = extension_for_codec(audio_codec)
    out_file = os.path.join("uploads", f"{uuid.uuid4().hex}{correct_ext}")

    extract_cmd = [
        "ffmpeg", "-i", file_path,
        "-vn",             # drop video
        "-acodec", "copy", # copy only audio track, no re-encode
        out_file,
        "-y"
    ]
    try:
        subprocess.run(extract_cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise_http_exception_once(
            e,
            500,
            f"FFmpeg error while extracting audio from {file_path}",
            f"The error: {str(e)}, in ensure_audio_only in youtube.py"
        )

    return out_file

# **New** function to unify download + transcribe logic
async def handle_audio_download_and_transcribe(local_path: str, url: str,task_id ,chunk_size: int = 1200) -> dict:
    """
    Downloads an audio file from 'url', ensures it is single audio-only,
    chunk & transcribe, then cleans up.
    """
    local_filename=local_path
    # local_filename = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}.mp3")
    # time.sleep(5)
    # response = requests.get(url, stream=True)
    # response.raise_for_status()
    # with open(local_filename, "wb") as f:
    #     for chunk in response.iter_content(chunk_size=8192):
    #         f.write(chunk)

    audio_only_file = ensure_audio_only(local_filename)
    print("ensure_audio_only => returned:", audio_only_file)
    try:
        print("Transcribing audio...")
        send_webhook_status(task_id, "Transcribing Audio", "event.transcribing_audio", True)
        transcription_result = await single_pass_chunk_and_transcribe(audio_only_file, chunk_size)
    except Exception as e:
        send_webhook_status(task_id, f"Transcribing Audio Failed - {str(e)}", "event.transcribing_audio", False)
        raise   

    # Cleanup
    safe_remove(audio_only_file)
    if audio_only_file != local_filename:
        safe_remove(local_filename)

    return transcription_result
