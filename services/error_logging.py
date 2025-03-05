import requests
import logging
import os
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

# ---------------------------------------------------------
# 1) Set up logger for local file logging
# ---------------------------------------------------------
logger = logging.getLogger("error_logger")
logger.setLevel(logging.ERROR)  # We'll record errors or above

# Create a file handler that appends to "error_log.txt"
file_handler = logging.FileHandler("error_log.txt")
file_handler.setLevel(logging.ERROR)

# Define a log format (time - level - message)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(file_handler)

class SlackReportedException(HTTPException):
    """
    Custom exception that indicates Slack has already been notified
    about this error. Higher-level code can detect this exception type
    and avoid sending duplicate Slack messages.
    """
    pass

def send_error_slack_message(error: str):
    """
    Sends a Slack alert with the given error string.
    """
    logger.error(error)
    slack_channel_id = os.getenv('SLACK_ERROR_CHANNEL_ID')
    slack_bot_key = os.getenv('SLACK_BOT_KEY')
    text = str(error)
    try:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": slack_channel_id, "text": text},
            headers={
                "Authorization": f"Bearer {slack_bot_key}",
                "Content-Type": "application/json",
            },
        )
        if response.json().get("ok"):
            return True
    except Exception as e:
        print("Slack error", e)

def log_error_once(exception_obj, error_message: str):
    """
    Calls 'send_error_slack_message(error_message)' only if
    'exception_obj' hasn't already been reported in this request flow.
    """
    already = getattr(exception_obj, "_already_reported", False)
    if not already:
        send_error_slack_message(error_message)
        setattr(exception_obj, "_already_reported", True)

def raise_http_exception_once(original_exception, status_code: int, detail: str, log_message: str):
    """
    1) Logs the 'original_exception' once (Slack + file)
    2) Raises a new HTTPException with the same 'detail',
       setting _already_reported = True so that upstream
       won't log it again.
    """
    log_error_once(original_exception, log_message)
    new_ex = HTTPException(status_code=status_code, detail=detail)
    new_ex._already_reported = True
    raise new_ex
