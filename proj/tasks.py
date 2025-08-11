# -*- coding: utf-8 -*-
from __future__ import absolute_import

import email
from sqlalchemy import *
from elasticsearch import Elasticsearch

from celery import Task
from proj.celery import app


class MessagesTask(Task):
    """Celery 抽象基类，封装了解析与部署内容的通用逻辑。"""

    abstract = True
    
    _messages_table = None
    _elasticsearch = None
    
    def _init_database(self):
        """初始化并确保 MySQL 数据库与表存在"""
    
        db = create_engine('mysql://root@localhost/messages')
        metadata = MetaData(db)
        messages_table = Table('messages', metadata,
                               Column('message_id', String(255), primary_key = True),
                               Column('subject', String(255)),
                               Column('to', String(255)),
                               Column('x_to', String(255)),
                               Column('from', String(255)),
                               Column('x_from', String(255)),
                               Column('cc', String(255)),
                               Column('x_cc', String(255)),
                               Column('bcc', String(255)),
                               Column('x_bcc', String(255)),
                               Column('payload', Text()))

        messages_table.create(checkfirst=True)
        
        self._messages_table = messages_table
        
    def _init_elasticsearch(self):
        """初始化 Elasticsearch 客户端"""
    
        self._elasticsearch = Elasticsearch()
        
    def parse_message_file(self, filename):
        """解析邮件文件，返回字典"""
    
        with open(filename) as f:
            message = email.message_from_file(f)
    
        return {'subject': message.get("Subject"),
                'to': message.get("To"),
                'x_to': message.get("X-To"),
                'from': message.get("From"),
                'x_from': message.get("X-From"),
                'cc': message.get("Cc"),
                'x_cc': message.get("X-cc"),
                'bcc': message.get("Bcc"),
                'x_bcc': message.get("X-bcc"),
                'message_id': message.get("Message-ID"),
                'payload': message.get_payload()}
        
    def database_insert(self, message_dict):
        """将消息字典写入 MySQL 数据库"""
        
        if self._messages_table is None:
            self._init_database()
            
        ins = self._messages_table.insert(values=message_dict)
        ins.execute()
        
    def elasticsearch_index(self, id, message_dict):
        """将消息写入 Elasticsearch 索引"""
        
        if self._elasticsearch is None:
            self._init_elasticsearch()
        
        self._elasticsearch.index(index="messages", doc_type="message", id=id, body=message_dict)


@app.task(base=MessagesTask, queue="parse")
def parse(filename):
    """解析邮件文件，返回字典"""
    
    # 调用基类方法并返回结果
    return parse.parse_message_file(filename)


@app.task(base=MessagesTask, queue="db_deploy", ignore_result=True)
def deploy_db(message_dict):
    """将消息字典部署到 MySQL 表"""
    
    # 调用基类方法
    deploy_db.database_insert(message_dict)


@app.task(base=MessagesTask, queue="es_deploy", ignore_result=True)
def deploy_es(message_dict):
    """将消息字典部署到 Elasticsearch 实例"""
    
    # 调用基类方法
    deploy_es.elasticsearch_index(message_dict['message_id'], message_dict)