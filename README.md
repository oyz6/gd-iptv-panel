# gd-iptv-panel

广东电信 IPTV 播放列表 + EPG 节目表面板。FastAPI + rtp2httpd，一键生成 M3U / XMLTV，内置链接健康检查与自动重建。

- 面板：`http://<host>:8686/`
- 播放列表：`http://<host>:8686/playlist.m3u`
- EPG：`http://<host>:8686/epg.xml`

---

## ✨ 特性

- **一键生成**：Web 面板填账号密码，点击生成，输出 `gdctiptv4.m3u` + `gdctepg.xml`
- **实时日志**：生成过程 stdout 流式回传
- **智能分组**：置顶 / 央视 / 广东 / 卫视 / 少儿 / CGTN / 超清4K / 其他
- **置顶副本**：置顶频道复制一份到顶部，原分组保留
- **EPG 兜底**：同组播源 / 频道别名 / 占位填充
- **外部源合并**：可合并第三方 M3U
- **链接健康检查**：定时抽样探测，失败率超阈值自动重建
- **全字段可配置**：所有参数（含高级项）都可在面板里改
- **多架构镜像**：`linux/amd64` + `linux/arm64`

---

## 🚀 快速开始

### 1. 前置条件

- Linux 主机（amd64 / arm64）
- Docker 24+（Compose v2 可选）
- 已部署 [rtp2httpd](https://github.com/tsl0922/rtp2httpd)（默认 `http://192.168.1.189:4022`）
- 运营商绑定好的机顶盒 MAC 和 IPTV 账号

### 2. 获取项目

```bash
git clone https://github.com/<你的用户名>/gd-iptv-panel.git
cd gd-iptv-panel
mkdir -p app/data
```

### 3. 启动

**方式 A：使用 docker-compose（推荐）**

```bash
docker compose up -d
docker compose logs -f gd-iptv-panel
```

**方式 B：使用 docker run**

```bash
docker run -d \
  --name gd-iptv-panel \
  --network host \
  --restart unless-stopped \
  -e TZ=Asia/Shanghai \
  -e IPTV_DATA_DIR=/data \
  -v $(pwd)/app/data:/data \
  ghcr.io/oyz6/gd-iptv-panel:latest
```

看到以下日志即成功：

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8686 (Press CTRL+C to quit)
```

### 4. 打开面板

访问 `http://<主机IP>:8686/`

默认账号：`admin` / `admin`（首次登录后建议修改）

### 5. 配置并生成

1. 登录后填写 **② IPTV 账号认证**：UserID、密码、MAC
2. 检查 **③ 网络与代理** 中 rtp2httpd 地址
3. 点击 **⚡ 一键生成**
4. 用播放器导入：`http://<主机IP>:8686/playlist.m3u`

---

## ⚙️ 配置说明

所有配置都可以在面板里改，保存到 `app/data/config.json`（首次启动自动从 `config.example.json` 生成）。

### 关键项

| 字段 | 说明 |
|---|---|
| `panel_username` / `panel_password` | 面板登录凭据 |
| `user_id` / `password` / `mac` | IPTV 账号（必填） |
| `rtp2httpd_url` | rtp2httpd 服务地址 |
| `fcc_server` | 默认 FCC 服务器 |
| `source_address` | 多网卡场景指定源 IP，留空走默认路由 |
| `epg_days_before` / `epg_days_after` | EPG 抓取时间窗 |
| `schedule_enabled` | 是否启用定时健康检查 |
| `health_fail_threshold` | 失败率阈值（超过才重建） |

完整参数见前端 **⚙ 高级设置**。

### 关于 `source_address`

只有主机有**多块网卡**、且系统默认路由选错导致运营商认证失败时才需要填。

判断方法：

```bash
ip route get 8.8.8.8   # 看 src= 后面是什么 IP
```

如果 `src` 不是 IPTV 专线网卡的 IP，把它填到面板 ③。

### 关于 `interface`

旧配置里有 `interface` 字段（如 `enp6s18`），模型保留但前端不显示，默认空字符串。当前生成脚本不使用它，可忽略。

---

## 🔌 API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/login` | 登录，返回 token |
| POST | `/api/logout` | 登出 |
| GET | `/api/auth-check` | 校验 token |
| GET | `/api/config` | 读取配置 |
| POST | `/api/config` | 部分更新配置 |
| GET | `/api/status` | 运行状态 + 输出文件列表 |
| POST | `/api/generate` | 触发生成 |
| GET | `/api/generate/status` | 生成进度（含 stdout） |
| POST | `/api/health-check` | 手动健康检查 |
| GET | `/playlist.m3u` | 下载播放列表 |
| GET | `/epg.xml` | 下载 EPG |

除 `/api/login`、`/api/auth-check`、`/playlist.m3u`、`/epg.xml` 外，其余需要请求头 `X-Auth-Token`。

---

## 🐳 使用预构建镜像

### 拉取镜像

```bash
docker pull ghcr.io/oyz6/gd-iptv-panel:latest
```

### 启动容器

```bash
docker run -d \
  --name gd-iptv-panel \
  --network host \
  --restart unless-stopped \
  -e TZ=Asia/Shanghai \
  -e IPTV_DATA_DIR=/data \
  -v $(pwd)/app/data:/data \
  ghcr.io/oyz6/gd-iptv-panel:latest
```

### 一行写法

```bash
docker run -d --name gd-iptv-panel --network host --restart unless-stopped -e TZ=Asia/Shanghai -e IPTV_DATA_DIR=/data -v /root/app/data:/data ghcr.io/oyz6/gd-iptv-panel:latest
```

> 注意 `-v` 参数用**绝对路径**更稳（如 `/root/app/data:/data`），避免 `$(pwd)` 受当前目录影响。

### 使用 docker-compose

新建 `docker-compose.yml`：

```yaml
services:
  gd-iptv-panel:
    image: ghcr.io/oyz6/gd-iptv-panel:latest
    container_name: gd-iptv-panel
    restart: unless-stopped
    network_mode: host
    environment:
      - TZ=Asia/Shanghai
      - IPTV_DATA_DIR=/data
    volumes:
      - ./app/data:/data
```

启动：

```bash
docker compose up -d
docker compose logs -f gd-iptv-panel
```

### GHCR 私有包的处理

如果 `docker pull` 报 `unauthorized` 或 `denied`：

**方式 1：登录 GHCR**

```bash
echo <你的GitHub_PAT> | docker login ghcr.io -u oyz6 --password-stdin
```

PAT 需要 `read:packages` 权限。

**方式 2：把包改成公开**

浏览器打开：

```
https://github.com/users/oyz6/packages/container/gd-iptv-panel/settings
```

→ 底部 Dangerous Zone → Change visibility → Public

---

## 🛠 常用管理命令

```bash
# 查看日志（实时）
docker logs -f gd-iptv-panel

# 查看最近 100 行
docker logs --tail=100 gd-iptv-panel

# 停止
docker stop gd-iptv-panel

# 启动
docker start gd-iptv-panel

# 重启
docker restart gd-iptv-panel

# 查看资源占用
docker stats gd-iptv-panel

# 删除容器（数据保留在宿主机）
docker rm -f gd-iptv-panel

# 更新到新版本
docker pull ghcr.io/oyz6/gd-iptv-panel:latest
docker rm -f gd-iptv-panel
# 然后重新执行 docker run 或 docker compose up -d
```

---

## 📂 数据目录

| 路径 | 说明 |
|---|---|
| `app/data/config.json` | 面板配置（首次启动自动生成） |
| `app/data/output/gdctiptv4.m3u` | 生成的播放列表 |
| `app/data/output/gdctepg.xml` | 生成的 EPG |
| `app/data/output/gdctepg.xml.gz` | EPG 压缩版（可选） |
| `app/data/health_samples.json` | 健康检查样本 |
| `app/data/output/exports/` | 外部源缓存 |

**重置数据**：

```bash
rm -rf app/data/output app/data/health_samples.json
# config.json 想留就留，想重置就一起删
```

---

## 🔄 发布新版本

```bash
git tag v1.0.0
git push origin v1.0.0
```

Actions（**🐳 构建并发布 gd-iptv-panel**）会自动：

1. 构建 `linux/amd64` + `linux/arm64` 镜像
2. 推送 4 个 tag：`v1.0.0`、`1.0.0`、`1.0`、`latest`
3. 在 Releases 里创建版本并附带源码 zip / tar.gz

**手动触发**（测试构建用）：

GitHub → Actions → 🐳 构建并发布 gd-iptv-panel → Run workflow

- `image_tag` 默认为 `dev`，可改成任何名字
- 只推镜像，不创建 Release

---

## 🔧 常见问题

### 容器报 `PermissionError: /data/output`

卷挂载覆盖了镜像权限。本项目默认容器以 root 运行，不会遇到。如果你改成非 root，需要：

```bash
sudo chown -R 1000:1000 app/data
```

### 认证失败 / 拉不到频道

- 确认 MAC 与运营商绑定的机顶盒一致
- 双网卡时尝试设置 `source_address`
- 查看生成日志里的具体错误码

### 播放列表能下载但播放器打不开

- 播放器需要能访问 `rtp2httpd_url` 里的 IP
- 检查 M3U 里的 URL 是否指向正确的局域网地址

### 端口冲突（host 网络模式下）

```bash
ss -tlnp | grep 8686
```

如果有其他进程占用 8686，先停掉它，或改用 bridge 网络：

```bash
docker run -d --name gd-iptv-panel -p 8686:8686 \
  -e IPTV_DATA_DIR=/data \
  -v /root/app/data:/data \
  ghcr.io/oyz6/gd-iptv-panel:latest
```

### 健康检查误报 / 漏报

- 误报多：调大 `health_timeout`，调小 `health_max_samples`
- 漏报多：调大 `health_max_samples`，调小 `health_fail_threshold`

---

## 📁 目录结构

```
gd-iptv-panel/
├── .github/workflows/release.yml  # 多架构镜像构建 + Release
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── app/
    ├── main.py                     # FastAPI 路由入口
    ├── core/                       # 配置 / 认证 / 任务状态
    ├── services/                   # 生成 / 健康 / 调度
    ├── models/                     # API schema
    ├── templates/gdctiptv.py.tmpl  # 生成模板（占位符注入）
    ├── static/index.html           # 前端面板
    └── data/
        ├── config.example.json     # 初始模板
        └── config.json             # 运行时生成（不入库）
```

---

## 📝 许可

仅供个人学习研究使用，请遵守当地法律法规和运营商服务条款。
```

---
