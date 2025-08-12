### 目标

- 在 CentOS 8 上从零安装 Docker，并在 Docker Swarm 下运行本邮件解析方案。
- 分两阶段：
  - 阶段1：本机（单节点）Swarm 验证
  - 阶段2：内网多节点（≥2 台 Linux）Swarm 部署

### 适用前提

- 系统：CentOS 8（或 CentOS Stream 8）。如遇 EOL 源问题，先按 `部署文档.md` 的“换源到 Vault”步骤切换到 `vault.centos.org`。
- 具备 sudo/root 权限，网络可访问内网镜像仓库或 Git 源。

### 一、在 CentOS 8 安装 Docker

1) 移除可能冲突的旧包

```bash
sudo dnf -y remove docker docker-client docker-client-latest docker-common docker-latest docker-latest-logrotate docker-logrotate docker-engine podman buildah || true
```

2) 安装依赖与 Docker 官方仓库

```bash
sudo dnf -y install yum-utils
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
```

3) 安装 Docker 引擎与 Compose 插件

```bash
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # 可选：免 sudo 使用 docker，重登生效
docker version && docker info | grep -E "Server Version|Cgroup"
```

如遇到仓库不可达/证书问题：

- 检查 DNS 与网络（参考“部署文档.md”的网络排查章节）。
- 使用离线/内网镜像仓库安装（替换 repo 地址或使用 RPM 包本地安装）。

### 二、开启/配置 Swarm 所需端口（防火墙）

单机可跳过；多节点需在所有节点放行：

```bash
sudo firewall-cmd --add-port=2377/tcp --permanent   # Swarm 管理端口（manager）
sudo firewall-cmd --add-port=7946/tcp --permanent   # 节点间通信（TCP）
sudo firewall-cmd --add-port=7946/udp --permanent   # 节点间通信（UDP）
sudo firewall-cmd --add-port=4789/udp --permanent   # VXLAN Overlay 网络
sudo firewall-cmd --reload

# 应用本方案对外端口（按需放行）
sudo firewall-cmd --add-port=5672/tcp --add-port=15672/tcp --add-port=6379/tcp --add-port=5432/tcp --add-port=9200/tcp --permanent
sudo firewall-cmd --reload
```

### 三、项目结构与镜像说明

- 应用镜像：`celery-message-processing:latest`（由 `docker/Dockerfile` 构建）
- 依赖服务：RabbitMQ、Redis、PostgreSQL 17、Elasticsearch 8（开发模式，关闭安全）
- 目录：
  - `docker/Dockerfile`：应用镜像
  - `docker/entrypoint-worker.sh`：可选 Worker 启动脚本
  - `docker/stack.yml`：Swarm 编排（拆分三类队列 Worker 与 fab 工具容器）

环境变量（可在 Stack 中覆盖）：

- `BROKER_URL`：`amqp://celery:celery@rabbitmq:5672//`
- `RESULT_BACKEND`：`redis://redis:6379/0`
- `DB_URL`：`postgresql+psycopg2://postgres:postgres@postgres:5432/messages`
- `ES_URL`：`http://elasticsearch:9200`

### 四、阶段1：本机单节点 Swarm

1) 构建镜像（在仓库根目录执行）

```bash
docker build -t test:latest -f docker/Dockerfile .
```

2) 初始化 Swarm（若未初始化）

```bash
docker swarm init
```

3) 部署 Stack（默认名 `mailproc`）

```bash
docker stack deploy -c docker/stack.yml mailproc
```

4) 查看服务与日志

```bash
docker stack services mailproc
docker service logs -f mailproc_worker_parse
docker service logs -f mailproc_worker_db
docker service logs -f mailproc_worker_es
```

5) 在 `fab` 容器中执行入队/查询

```bash
# 进入 fab 容器
docker ps --filter name=mailproc_fab -q | head -n1 | xargs -I{} docker exec -it {} bash

# 在容器内执行（/app 为工作目录）
fab workers --action=restart   # 可选：检查 workers 状态
fab process-one --filename=/app/sample.eml
fab query-db --query="SELECT COUNT(*) FROM messages;"
fab query-es --query="*:*"
```

6) 验证端口/服务

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
curl -sf http://localhost:15672 || true   # RabbitMQ 管理
curl -sf http://localhost:9200 || true    # Elasticsearch
```

### 五、阶段2：多节点 Swarm（≥2 台 Linux）

前提：所有节点均完成“安装 Docker”、“防火墙放行”。

1) 在管理节点初始化 Swarm

```bash
docker swarm init --advertise-addr <MANAGER_IP>
docker swarm join-token worker  # 获取 worker 加入命令
```

2) 在工作节点加入 Swarm

```bash
docker swarm join --token <WORKER_TOKEN> <MANAGER_IP>:2377
```

3) 分发应用镜像（两种方式，二选一）

- 方式A：每台节点本地构建同名镜像

  ```bash
  # 在每台节点：将代码拷贝/拉取到相同路径
  docker build -t celery-message-processing:latest -f docker/Dockerfile .
  ```
- 方式B：搭建内网 registry 并推送镜像

  ```bash
  # 在管理节点临时启动 registry（示例 5000 端口）
  docker run -d --restart=always -p 5000:5000 --name registry registry:2

  # 构建并推送
  docker build -t celery-message-processing:latest -f docker/Dockerfile .
  docker tag celery-message-processing:latest <REGISTRY_HOST>:5000/celery-message-processing:latest
  docker push <REGISTRY_HOST>:5000/celery-message-processing:latest

  # 修改 docker/stack.yml 中所有应用服务的 image 字段为 <REGISTRY_HOST>:5000/celery-message-processing:latest
  # 注意：Swarm 会忽略 build 字段，必须确保各节点可拉取到镜像
  ```

4) 部署 Stack（管理节点执行）

```bash
docker stack deploy -c docker/stack.yml mailproc
docker stack services mailproc
```

5) 扩缩容与节点调度

```bash
docker service scale mailproc_worker_parse=2 mailproc_worker_db=2 mailproc_worker_es=2
# 可在 stack.yml 中通过 placement/labels 设置节点亲和性或反亲和性
```

6) 运行任务

```bash
# 在管理节点查找一个 fab 容器并进入
docker ps --filter name=mailproc_fab -q | head -n1 | xargs -I{} docker exec -it {} bash
fab process --path=/app/data/maildir
```

### 六、数据持久化与生产建议

- PostgreSQL 使用命名卷 `pgdata`；生产建议改为外部存储（NFS、CephFS、云盘），并定期备份。
- Elasticsearch 当前使用单节点开发模式（关闭安全）。生产请改为多节点并开启 xpack 安全，配置账号密码。
- 建议将 DB/ES/RabbitMQ 凭据改用 Swarm secrets/configs 管理。
- 可将三个队列 Worker 分别设置不同副本数与并发，以提升吞吐与隔离性。

### 七、常见问题排查

- 部署失败/服务镜像拉取失败：确保每个节点都能获取 `celery-message-processing:latest`（方式A 本地构建，或方式B 内网 registry）。
- 端口占用：调整 `docker/stack.yml` 中端口映射，或释放宿主机冲突端口。
- Elasticsearch 内存不足：在 `docker/stack.yml` 下调 `ES_JAVA_OPTS`（如 `-Xms256m -Xmx256m`），并确保 `deploy.resources.limits.memory` 足够。
- Swarm 节点无法互通：检查防火墙是否放行 2377/tcp、7946/tcp、7946/udp、4789/udp；确认节点间网络与时间同步。

### 八、运维常用命令

```bash
docker stack ls
docker stack services mailproc
docker stack ps mailproc
docker service logs -f mailproc_worker_parse
docker service update --image <NEW_IMAGE> mailproc_worker_db
docker stack rm mailproc
```

### 九、国内镜像加速/修复（官方源/Hub 大陆直连失败时）

已完成“二、安装依赖与 Docker 官方仓库”（即已生成 `/etc/yum.repos.d/docker-ce.repo`）但下载失败时，可按以下步骤切换国内镜像并启用拉取加速：

1) 将 Docker CE YUM 源切换到国内镜像（以阿里云为例）

```bash
sudo sed -i 's|download.docker.com|mirrors.aliyun.com/docker-ce|g' /etc/yum.repos.d/docker-ce.repo
sudo sed -i 's|https://download.docker.com/linux/centos/gpg|https://mirrors.aliyun.com/docker-ce/linux/centos/gpg|g' /etc/yum.repos.d/docker-ce.repo
sudo yum clean all && sudo yum makecache

# 重新安装（或继续执行第三步）
sudo yum -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

可替换为其他镜像源（任选其一）：

- USTC: 将域名替换为 `mirrors.ustc.edu.cn/docker-ce`
- 清华: 将域名替换为 `mirrors.tuna.tsinghua.edu.cn/docker-ce`（如可用）

2) 配置 Docker Hub 拉取加速（daemon 级镜像源）

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://mirror.ccs.tencentyun.com",
    "https://hub-mirror.c.163.com",
    "https://f1361db2.m.daocloud.io"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker

# 验证
docker pull hello-world
```

说明：部分公共镜像站可能随政策变动失效，若持续失败，建议：

- 使用阿里云容器镜像服务个人专属加速器（在控制台获取专属地址，替换到 `registry-mirrors`）。
- 在有外网的机器预拉取镜像并离线导入：
  ```bash
  # 外网机器
  docker pull rabbitmq:3-management
  docker pull redis:7-alpine
  docker pull postgres:17
  docker pull docker.elastic.co/elasticsearch/elasticsearch:8.13.4
  docker save rabbitmq:3-management redis:7-alpine postgres:17 docker.elastic.co/elasticsearch/elasticsearch:8.13.4 -o deps-images.tar

  # 目标机器（内网）
  docker load -i deps-images.tar
  ```
- 在内网搭建私有 registry，将镜像推送到内网后在 `docker/stack.yml` 中改用内网镜像地址（见“阶段2/方式B”）。
