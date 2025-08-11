# -*- coding: utf-8 -*-
from __future__ import absolute_import

from celery import Celery

app = Celery('proj',
             broker='amqp://',
             backend='redis://localhost',
             include=['proj.tasks'])

# 可选配置，详见应用程序用户指南
app.conf.update(
    CELERY_TASK_RESULT_EXPIRES=3600,
)

if __name__ == '__main__':
    app.start()