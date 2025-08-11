# -*- coding: utf-8 -*-
from __future__ import absolute_import

import os
from celery import Celery

BROKER_URL = os.getenv("BROKER_URL", "amqp://guest:guest@localhost:5672//")
RESULT_BACKEND = os.getenv("RESULT_BACKEND", "redis://localhost:6379/0")

app = Celery(
    "proj",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["proj.tasks"],
)

# Celery 5 推荐配置键
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
)

if __name__ == "__main__":
    app.start()