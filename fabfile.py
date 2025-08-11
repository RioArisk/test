# -*- coding: utf-8 -*-
import os

from fabric.api import local

from celery import chain, group
from celery.task.control import inspect
from proj.tasks import parse, deploy_db, deploy_es

def workers(action):
    """启动、重启或停止 Celery worker 的命令"""
    
    # 准备用于存放 PID 和日志的目录
    local("mkdir -p celery-pids celery-logs")
    
    # 启动 4 个 Celery worker，分别对应 4 个队列（parse、db_deploy、es_deploy、默认）
    # 除默认队列外，每个并发数为 2；默认队列并发数为 1
    # 该命令格式的更多信息见：
    # http://docs.celeryproject.org/en/latest/reference/celery.bin.multi.html
    
    local("celery multi {} parse db_deploy es_deploy celery "\
          "-Q:parse parse -Q:db_deploy db_deploy -Q:es_deploy es_deploy -Q:celery celery "\
          "-c 2 -c:celery 1 "\
          "-l info -A proj "\
          "--pidfile=celery-pids/%n.pid --logfile=celery-logs/%n.log".format(action))
    
def inspect_workers():
    """显示 workers 与队列的信息"""
    
    i = inspect()
    
    print i.scheduled()
    print i.active()
    
def process_one(filename=None):
    """将单个邮件文件加入队列进行处理"""
    
    res = chain(parse.s(filename), group(deploy_db.s(), deploy_es.s()))()
    
    print "Enqueued mail file for processing: {} ({})".format(filename, res)
    
def process(path=None):
    """将邮件文件加入队列处理；若传入目录，则会递归将目录下所有文件加入队列"""
    
    if os.path.isfile(path):
        process_one(path)
    elif os.path.isdir(path):
        for subpath, subdirs, files in os.walk(path):
            for name in files:
                process_one(os.path.join(subpath, name))
    
def query_es(query="*:*"):
    """查询本地 Elasticsearch 实例"""
    
    local("curl 'http://localhost:9200/_search?q={}&pretty=true'".format(query))
    
def query_db(query="SELECT COUNT(*) FROM messages"):
    """查询本地 MySQL 数据库"""
    
    local("mysql -u root -e '{}' messages".format(query))
    
def purge():
    """清空 Elasticsearch 索引与 MySQL 表中的数据"""
    
    local("curl -XDELETE 'http://localhost:9200/messages/?pretty=true'")
    local("mysql -u root -e 'DROP TABLE IF EXISTS messages' messages")