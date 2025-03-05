# celeryapp.py
import os
from celery import Celery

# Example: read broker/backends from environment or default to local Redis
BROKER_URL = os.getenv("CELERY_BROKER_URL")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND")

celery = Celery(
    "video_render",
    broker=BROKER_URL,
    backend=RESULT_BACKEND
)

celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    worker_prefetch_multiplier=1,  # avoids one worker grabbing too many tasks at once
    broker_transport_options={'visibility_timeout': 3600},  # 1 hour
    imports=("tasks",),
)
