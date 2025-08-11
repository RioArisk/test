# -*- coding: utf-8 -*-
import os
from pathlib import Path

from fabric import task
from celery import chain, group
from proj.celery import app as celery_app
from proj.tasks import parse, deploy_db, deploy_es


@task
def workers(c, action="start"):
    """启动、重启或停止 Celery worker 的命令

    使用示例：
      fab workers --action=start|restart|stop
    """

    Path("celery-pids").mkdir(parents=True, exist_ok=True)
    Path("celery-logs").mkdir(parents=True, exist_ok=True)

    c.run(
        "celery multi {} parse db_deploy es_deploy celery "
        "-Q:parse parse -Q:db_deploy db_deploy -Q:es_deploy es_deploy -Q:celery celery "
        "-c 2 -c:celery 1 "
        "-l info -A proj "
        "--pidfile=celery-pids/%n.pid --logfile=celery-logs/%n.log".format(action),
        pty=True,
    )


@task
def inspect_workers(c):
    """显示 workers 与队列的信息"""

    i = celery_app.control.inspect()
    print(i.scheduled())
    print(i.active())


@task
def process_one(c, filename=None):
    """将单个邮件文件加入队列进行处理"""

    res = chain(parse.s(filename), group(deploy_db.s(), deploy_es.s()))()
    print("Enqueued mail file for processing: {} ({})".format(filename, res))


@task
def process(c, path=None):
    """将邮件文件加入队列处理；若传入目录，则会递归将目录下所有文件加入队列"""

    if path is None:
        raise SystemExit("请提供 path 参数，例如: fab process --path=/path/to/maildir")

    if os.path.isfile(path):
        process_one(c, path)
    elif os.path.isdir(path):
        for subpath, _subdirs, files in os.walk(path):
            for name in files:
                process_one(c, os.path.join(subpath, name))
    else:
        raise SystemExit("提供的 path 不存在: {}".format(path))


@task
def query_es(c, query="*:*"):
    """查询 Elasticsearch 实例（默认 http://localhost:9200）"""

    es_url = os.getenv("ES_URL", "http://localhost:9200")
    c.run("curl '{}/_search?q={}&pretty=true'".format(es_url, query), pty=True)


@task
def query_db(c, query="SELECT COUNT(*) FROM messages"):
    """查询 PostgreSQL 数据库（默认 postgresql://postgres:postgres@localhost:5432/messages）"""

    db_url = os.getenv(
        "DB_URL", "postgresql://postgres:postgres@localhost:5432/messages"
    )
    c.run("psql '{}' -c \"{}\"".format(db_url, query.replace("\"", "\\\"")), pty=True)


@task
def purge(c):
    """清空 Elasticsearch 索引与 PostgreSQL 表中的数据"""

    es_url = os.getenv("ES_URL", "http://localhost:9200")
    db_url = os.getenv(
        "DB_URL", "postgresql://postgres:postgres@localhost:5432/messages"
    )

    c.run("curl -XDELETE '{}/messages/?pretty=true'".format(es_url), pty=True)
    c.run(
        "psql '{}' -c \"DROP TABLE IF EXISTS messages;\"".format(db_url), pty=True
    )