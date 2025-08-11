# -*- coding: utf-8 -*-
from __future__ import absolute_import

import email
from typing import Any, Dict

from sqlalchemy import (
    Table,
    Column,
    MetaData,
    String,
    Text,
    create_engine,
    insert,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from elasticsearch import Elasticsearch

from celery import Task
from proj.celery import app


class MessagesTask(Task):
    """Celery 抽象基类，封装了解析与部署内容的通用逻辑。"""

    abstract = True
    
    _messages_table: Table = None
    _elasticsearch: Elasticsearch = None
    _engine: Engine = None
    
    def _init_database(self) -> None:
        """初始化并确保 PostgreSQL 数据库与表存在。

        连接串默认使用：postgresql+psycopg2://postgres:postgres@localhost:5432/messages
        可通过环境变量覆盖：DB_URL
        """

        import os

        db_url = os.getenv(
            "DB_URL",
            "postgresql+psycopg2://postgres:postgres@localhost:5432/messages",
        )

        engine = create_engine(db_url, future=True)
        metadata = MetaData()
        messages_table = Table(
            "messages",
            metadata,
            Column("message_id", String(255), primary_key=True),
            Column("subject", String(255)),
            Column("to", String(255)),
            Column("x_to", String(255)),
            Column("from", String(255)),
            Column("x_from", String(255)),
            Column("cc", String(255)),
            Column("x_cc", String(255)),
            Column("bcc", String(255)),
            Column("x_bcc", String(255)),
            Column("payload", Text()),
        )

        metadata.create_all(engine)

        self._engine = engine
        self._messages_table = messages_table
        
    def _init_elasticsearch(self) -> None:
        """初始化 Elasticsearch 客户端。

        默认连接到本地 http://localhost:9200，可通过环境变量 ES_URL 覆盖。
        兼容 Elasticsearch 7/8，在写入时同时适配 body/document 参数。
        """

        import os

        es_url = os.getenv("ES_URL", "http://localhost:9200")
        self._elasticsearch = Elasticsearch(es_url)
        
    def parse_message_file(self, filename: str) -> Dict[str, Any]:
        """解析邮件文件，返回字典"""

        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            message = email.message_from_file(f)

        return {
            "subject": message.get("Subject"),
            "to": message.get("To"),
            "x_to": message.get("X-To"),
            "from": message.get("From"),
            "x_from": message.get("X-From"),
            "cc": message.get("Cc"),
            "x_cc": message.get("X-cc"),
            "bcc": message.get("Bcc"),
            "x_bcc": message.get("X-bcc"),
            "message_id": message.get("Message-ID"),
            "payload": message.get_payload(),
        }
        
    def database_insert(self, message_dict: Dict[str, Any]) -> None:
        """将消息字典写入 PostgreSQL 数据库"""

        if self._messages_table is None or self._engine is None:
            self._init_database()

        try:
            with self._engine.begin() as conn:
                stmt = insert(self._messages_table).values(**message_dict)
                conn.execute(stmt)
        except SQLAlchemyError as exc:
            print(f"数据库写入失败: {exc}")
        
    def elasticsearch_index(self, id: str, message_dict: Dict[str, Any]) -> None:
        """将消息写入 Elasticsearch 索引（兼容 7/8）。"""

        if self._elasticsearch is None:
            self._init_elasticsearch()

        try:
            self._elasticsearch.index(index="messages", id=id, document=message_dict)
        except TypeError:
            self._elasticsearch.index(index="messages", id=id, body=message_dict)


@app.task(bind=True, base=MessagesTask, queue="parse")
def parse(self, filename):
    """解析邮件文件，返回字典"""

    return self.parse_message_file(filename)


@app.task(bind=True, base=MessagesTask, queue="db_deploy", ignore_result=True)
def deploy_db(self, message_dict):
    """将消息字典部署到 PostgreSQL 表"""

    self.database_insert(message_dict)


@app.task(bind=True, base=MessagesTask, queue="es_deploy", ignore_result=True)
def deploy_es(self, message_dict):
    """将消息字典部署到 Elasticsearch 实例"""

    self.elasticsearch_index(message_dict['message_id'], message_dict)