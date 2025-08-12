FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖尽量精简（使用 psycopg2-binary 避免编译 libpq）
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 优先安装 Python 依赖（提升构建缓存命中率）
COPY celery-message-processing/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

# 复制应用代码
COPY celery-message-processing/proj /app/proj
COPY celery-message-processing/fabfile.py /app/fabfile.py

# 默认环境变量（可在 Swarm Stack 中覆盖）
ENV BROKER_URL=amqp://celery:celery@rabbitmq:5672// \
    RESULT_BACKEND=redis://redis:6379/0 \
    DB_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/messages \
    ES_URL=http://elasticsearch:9200

# Worker 入口脚本（可按队列配置）
COPY docker/entrypoint-worker.sh /usr/local/bin/entrypoint-worker.sh
RUN chmod +x /usr/local/bin/entrypoint-worker.sh

# 默认命令仅显示帮助；实际服务会在 Stack 中用 entrypoint/command 覆盖
CMD ["bash", "-lc", "celery --help && echo 'Use entrypoint-worker.sh for workers or run fab ...'"]

