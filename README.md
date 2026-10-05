# 广东电信 IPTV 播放列表 + EPG 面板，**单个 Rust 二进制**，内置 RTSP/UDP 代理。

[![Release](https://img.shields.io/github/v/release/oyz6/gd-iptv-panel?label=release)](https://github.com/oyz6/gd-iptv-panel/releases/latest)
[![Build](https://github.com/oyz6/gd-iptv-panel/actions/workflows/release.yml/badge.svg)](https://github.com/oyz6/gd-iptv-panel/actions/workflows/release.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#许可)

- 面板：`http://<host>:4022/`
- 播放列表：`http://<host>:4022/playlist`
- EPG：`http://<host>:4022/xmltv`

---

## ✨ 特性

- 🚀 **单二进制** — 约 1.6 MB，无 Python、无 Node、无 Docker 依赖（可选）
- 🔌 **内置代理** — RTSP / UDP 组播转 HTTP，**不需要 rtp2httpd / udpxy**
- 🖥 **Web UI** — 所有配置在浏览器里改，实时保存，深浅主题
- 📺 **智能分组** — 置顶 / 央视 / 广东 / 卫视 / 少儿 / CGTN / 超清4K / 其他
- 📌 **置顶副本** — 置顶频道复制一份到顶部，原分组保留
- 🌐 **外部源合并** — 支持合并第三方 M3U
- 🔐 **Token 认证** — 面板登录 + API 鉴权
- 🏗 **多架构** — `linux/amd64` + `linux/arm64`
- 🎨 **SVG 图标** — 无 emoji 依赖，深浅主题自动切换

---

## 🚀 快速开始

### 前置条件

#### 🔐 IPTV 账号必须由机顶盒注册

- 广东电信 IPTV 的业务认证**绑定机顶盒硬件信息**（MAC 地址）
- 光猫注册 / 路由器注册的账号**无法用于本项目**
- 本项目相当于**模拟一台已注册的机顶盒**去运营商侧拉流，必须使用**已绑定机顶盒的真实 MAC 和账号密码**

#### 💻 部署主机

- 任意能跑 Linux 二进制的主机（amd64 / arm64）：
  - 软路由（OpenWrt / iStoreOS / Armbian）
  - NAS（群晖 / 威联通 / TrueNAS）
  - 树莓派 / N100 小主机 / 迷你 PC
- **网络要求**：主机必须**与机顶盒在同一网络层级**（同 VLAN / 同子网），能够直接收发 IGMP 组播流量

#### 📋 需要准备的信息

| 信息 | 说明 | 从哪获取 |
|---|---|---|
| **IPTV 账号 (UserID)** | 运营商下发的宽带账号 | 机顶盒设置界面 / 运营商合同 |
| **IPTV 密码** | 与 UserID 配套的认证密码 | 机顶盒设置界面 / 运营商合同 |
| **机顶盒 MAC** | 已注册的机顶盒网卡 MAC | 机顶盒背面标签 / 设置界面 |

---

### 方式一：一键安装脚本（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/oyz6/gd-iptv-panel/rust/install.sh | sudo bash
```

或先下载再运行：

```bash
wget https://raw.githubusercontent.com/oyz6/gd-iptv-panel/rust/install.sh
chmod +x install.sh
sudo ./install.sh
```

安装完成后访问 `http://<主机IP>:4022/`，默认账号 `admin` / `admin`。

#### 脚本管理命令

```bash
sudo ./install.sh              # 安装或升级
sudo ./install.sh upgrade      # 升级到最新版本
sudo ./install.sh restart      # 重启服务
sudo ./install.sh status       # 查看状态
sudo ./install.sh logs         # 查看实时日志
sudo ./install.sh version      # 查看版本
sudo ./install.sh uninstall    # 卸载
```

---

### 方式二：手动安装

#### 1. 下载二进制

从 [Releases](https://github.com/oyz6/gd-iptv-panel/releases/latest) 下载对应架构：

```bash
# x86_64 (amd64)
wget https://github.com/oyz6/gd-iptv-panel/releases/latest/download/gd-iptv-panel-linux-amd64

# 或 arm64
wget https://github.com/oyz6/gd-iptv-panel/releases/latest/download/gd-iptv-panel-linux-arm64
```

**查看自己主机的架构**：

```bash
uname -m
# x86_64  → 用 amd64
# aarch64 → 用 arm64
```

#### 2. 加执行权限

```bash
chmod +x gd-iptv-panel-linux-amd64
mv gd-iptv-panel-linux-amd64 gd-iptv-panel
```

#### 3. 直接运行（快速测试）

```bash
./gd-iptv-panel -c ./config.json
```

首次运行会自动生成 `config.json`（含默认值），浏览器打开 `http://<主机IP>:4022/` 配置。

#### 4. 安装为 systemd 服务（正式使用）

```bash
# 安装二进制
sudo install -m 755 gd-iptv-panel /usr/local/bin/gd-iptv-panel

# 创建配置目录
sudo mkdir -p /etc/gd-iptv-panel

# 创建 systemd 服务
sudo tee /etc/systemd/system/gd-iptv-panel.service > /dev/null <<'EOF'
[Unit]
Description=gd-iptv-panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/gd-iptv-panel -c /etc/gd-iptv-panel/config.json
Restart=on-failure
RestartSec=5
Environment=RUST_LOG=info,actix_http=warn

[Install]
WantedBy=multi-user.target
EOF

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable --now gd-iptv-panel

# 查看状态
sudo systemctl status gd-iptv-panel
```

---

### 方式三：Docker

```bash
docker run -d \
  --name gd-iptv-panel \
  --network host \
  --restart unless-stopped \
  -e TZ=Asia/Shanghai \
  -v /root/gd-iptv-panel:/data \
  ghcr.io/oyz6/gd-iptv-panel:latest
```

**docker-compose.yml**：

```yaml
services:
  gd-iptv-panel:
    image: ghcr.io/oyz6/gd-iptv-panel:latest
    container_name: gd-iptv-panel
    restart: unless-stopped
    network_mode: host
    environment:
      - TZ=Asia/Shanghai
      - IPTV_CONFIG=/data/config.json
    volumes:
      - ./data:/data
```

---

## ⚙️ 首次配置

浏览器打开 `http://<主机IP>:4022/`，默认账号 `admin` / `admin`。

### 面板填写清单

| 卡片 | 内容 | 必填 |
|---|---|---|
| **① 面板登录** | 改掉默认账号密码（**强烈建议**） | 建议 |
| **② IPTV 账号认证** | UserID / 密码 / 机顶盒 MAC | **必填** |
| **③ 内置代理** | 勾选 UDP 代理 或 RTSP 代理 | **必填** |
| **④ 输出选项** | 播放列表 / EPG / 频道图标 / 置顶副本 | 建议全勾 |
| **⑤ 外部 M3U 源** | 合并第三方 M3U（按需） | 可选 |

点 **保存配置** 后生效。

### 代理方式选择

| 场景 | 推荐 | 说明 |
|---|---|---|
| 运营商支持 **UDP 组播** | 勾 **UDP 代理** | 需要主机能收到 IGMP 组播 |
| 运营商支持 **RTSP** | 勾 **RTSP 代理** | 兼容性更好 |
| 时移回看 | 两个都勾 + 勾"生成时移回看" | 回看依赖 RTSP |

---

## 📺 播放器导入

| 类型 | 地址 |
|---|---|
| **M3U 播放列表** | `http://<主机IP>:4022/playlist` |
| **EPG** | `http://<主机IP>:4022/xmltv` |

**注意**：EPG 通常会自动从 M3U 里的 `x-tvg-url` 属性读取，不用单独配置。如果播放器不自动读，手动填 `/xmltv` 地址。

### 常见播放器

- **VLC** — 媒体 → 打开网络串流 → 粘贴 M3U 地址
- **PotPlayer** — 打开 → 打开链接 → 粘贴
- **TiviMate** — 设置 → 播放列表 → 添加 M3U
- **云影空蒙 / Kodi / Emby** — 直接添加 M3U 源

---

## 🔧 命令行参数

```text
Usage: gd-iptv-panel [OPTIONS]

Options:
  -c, --config <CONFIG>    配置文件路径 [default: ./config.json]
  -b, --bind <BIND>        监听地址（覆盖配置文件）
  -h, --help               显示帮助
  -V, --version            显示版本
```

**示例**：

```bash
# 使用默认配置
./gd-iptv-panel

# 指定配置文件
./gd-iptv-panel -c /etc/gd-iptv-panel/config.json

# 临时改端口
./gd-iptv-panel -b 0.0.0.0:9000
```

---

## 📂 配置文件

首次运行会自动生成 `config.json`。**大多数配置建议在 Web 面板里改**，只有 `bind` 需要在启动前手动调整。

### 完整字段说明

```json
{
  "bind": "0.0.0.0:4022",
  "admin_user": "admin",
  "admin_pass": "admin",

  "iptv": {
    "user": "XXXXXXXXX",
    "passwd": "XXXXXXXX",
    "mac": "a3:11:22:33:44:b3",
    "imei": "",
    "address": "",
    "interface": null
  },

  "proxy": {
    "udp_proxy": true,
    "rtsp_proxy": false,
    "include_catchup": true,
    "playseek_template": "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"
  },

  "output": {
    "enable_playlist": true,
    "enable_xmltv": true,
    "enable_logo": true,
    "enable_top_channels": true
  },

  "external": {
    "enabled": false,
    "url": "",
    "timeout_seconds": 15,
    "merge_into_playlist": true
  }
}
```

### 关键字段

| 字段 | 说明 |
|---|---|
| `bind` | 监听地址，**改后需重启服务** |
| `admin_user` / `admin_pass` | 面板登录凭据 |
| `iptv.user` / `passwd` / `mac` | IPTV 账号（必填） |
| `iptv.interface` | 多网卡时指定，如 `eth0`，留 null 走默认 |
| `proxy.udp_proxy` | 启用 UDP 组播转 HTTP |
| `proxy.rtsp_proxy` | 启用 RTSP 转 HTTP |
| `proxy.include_catchup` | 生成时移回看链接 |
| `output.enable_top_channels` | 是否输出置顶频道副本 |
| `external.enabled` | 是否合并外部 M3U |
| `external.url` | 外部 M3U 地址 |

### 修改端口

```bash
# 编辑配置文件
sudo vi /etc/gd-iptv-panel/config.json
# 把 "bind": "0.0.0.0:4022" 改成 "0.0.0.0:9000"

# 重启服务
sudo systemctl restart gd-iptv-panel
```

---

## 🔌 API 端点

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| GET | `/` | ❌ | Web 面板 |
| POST | `/api/login` | ❌ | 登录，返回 token |
| POST | `/api/logout` | ✅ | 登出 |
| GET | `/api/auth-check` | ❌ | 校验 token |
| GET | `/api/config` | ✅ | 读取配置 |
| POST | `/api/config` | ✅ | 更新配置 |
| GET | `/api/status` | ✅ | 运行状态 |
| GET | `/playlist` | ❌ | M3U 播放列表 |
| GET | `/xmltv` | ❌ | XMLTV EPG |
| GET | `/logo/{id}.png` | ❌ | 频道图标 |
| GET | `/rtsp/{path}` | ❌ | RTSP 代理 |
| GET | `/udp/{addr}` | ❌ | UDP 组播代理 |

**需要认证的接口**必须带请求头：

```
X-Auth-Token: <token>
```

**登录示例**：

```bash
TOKEN=$(curl -s -X POST http://localhost:4022/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | jq -r .token)

curl -s http://localhost:4022/api/config -H "X-Auth-Token: $TOKEN" | jq
```

---

## 🛠 常用命令

```bash
# 服务管理
sudo systemctl start gd-iptv-panel
sudo systemctl stop gd-iptv-panel
sudo systemctl restart gd-iptv-panel
sudo systemctl status gd-iptv-panel

# 日志
sudo journalctl -u gd-iptv-panel -f              # 实时
sudo journalctl -u gd-iptv-panel -n 50           # 最近 50 行
sudo journalctl -u gd-iptv-panel --since "1h ago" # 最近 1 小时

# 端口检查
ss -tlnp | grep 4022

# 本机测试
curl -sI http://127.0.0.1:4022/playlist
```

---

## 🔄 升级

```bash
sudo ./install.sh upgrade
```

或手动：

```bash
# 下载新版
wget https://github.com/oyz6/gd-iptv-panel/releases/latest/download/gd-iptv-panel-linux-amd64
chmod +x gd-iptv-panel-linux-amd64

# 停止服务
sudo systemctl stop gd-iptv-panel

# 替换
sudo install -m 755 gd-iptv-panel-linux-amd64 /usr/local/bin/gd-iptv-panel

# 启动
sudo systemctl start gd-iptv-panel
```

配置文件 **不会被覆盖**。

---

## 🔧 常见问题

### 认证失败 / 拉不到频道

- **MAC 必须**与运营商绑定的机顶盒一致，不能随便写
- 光猫 / 路由器里注册的账号**用不了**，必须用机顶盒的账号
- 多网卡主机尝试在 ② 里填 `interface`（如 `eth0`）
- 查看日志：`sudo journalctl -u gd-iptv-panel -n 50`

### 端口 4022 被占用

```bash
ss -tlnp | grep 4022
```

查出占用进程后停掉，或改配置文件的 `bind` 字段换端口。

### 面板打不开

1. 检查服务状态：`sudo systemctl status gd-iptv-panel`
2. 检查防火墙：
   - Ubuntu/Debian：`sudo ufw allow 4022`
   - CentOS/Fedora：`sudo firewall-cmd --add-port=4022/tcp --permanent && sudo firewall-cmd --reload`
3. 用 `curl -sI http://127.0.0.1:4022/` 本机测试

### 日志里出现 `invalid HTTP version specified`

**无害**。这是外部端口扫描或非 HTTP 客户端连接导致的。加环境变量可隐藏：

```ini
[Service]
Environment=RUST_LOG=info,actix_http=warn
```

### 复制按钮点了没反应

HTTP 环境下浏览器禁用了剪贴板 API。**点击地址框全选后 `Ctrl+C` 手动复制**即可。或者用 `http://localhost:4022/` 本机访问时可用。

### 播放列表能下载但播放器打不开

- 播放器需要能访问到 `gd-iptv-panel` 的地址
- 检查防火墙是否放行了 4022
- 检查播放器是否能访问到 M3U 里的流地址

### SELinux 阻止执行（CentOS / RHEL）

```bash
sudo semanage fcontext -a -t bin_t "/usr/local/bin/gd-iptv-panel"
sudo restorecon -v /usr/local/bin/gd-iptv-panel
```

或临时关闭：`sudo setenforce 0`

---

## 🌳 分支说明

本项目使用双分支结构：

| 分支 | 内容 |
|---|---|
| **`main`**（当前） | 构建工作流 + 安装脚本 + 本文档 |
| **`rust`** | 完整源代码（Cargo.toml / src / static） |

### 查看源码

```bash
git clone -b rust https://github.com/oyz6/gd-iptv-panel.git
cd gd-iptv-panel
```

### 自行编译

```bash
# 安装 Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 编译（release）
cargo build --release --features rustls

# 产物在
./target/release/gd-iptv-panel
```

### 触发自动构建

GitHub → Actions → **🦀 构建 gd-iptv-panel** → **Run workflow**

- `ref`：代码分支，默认 `rust`
- `tag_suffix`：可选，给 tag 加后缀（如 `beta`）

构建完成后会自动生成 Release，tag 格式为 `v{版本号}-{时间戳}`，例如 `v0.2.0-20261004-2143`。

---

## 📊 与 Python 版对比

| 项 | Rust 版（本项目） | Python 版 |
|---|---|---|
| 二进制大小 | **~1.6 MB** | ~200 MB |
| 内存占用 | **几 MB** | 50-100 MB |
| 内置代理 | ✅ | ❌ 需 rtp2httpd |
| 部署复杂度 | **单文件** | Docker + rtp2httpd |
| Web UI | ✅ | ✅ |
| 频道分组 | ✅ | ✅ |
| 外部源 | ✅ | ✅ |

---

## 🗺 路线图

- [x] 单二进制 + 内置代理
- [x] Web UI（深浅主题）
- [x] 频道分组 + 置顶副本
- [x] 外部源合并
- [ ] EPG 本地缓存（减少上游压力）
- [ ] 频道分组关键词自定义
- [ ] 定时任务（每天固定时刻刷新）
- [ ] 健康检查

---

## 📝 许可

仅供个人学习研究使用，请遵守当地法律法规和运营商服务条款。

---

## 🙏 致谢

- 生成逻辑参考 [iptv-proxy](https://github.com/yujincheng08/iptv-proxy)
- 内置代理基于 [retina](https://github.com/yujincheng08/retina)
- 感谢所有贡献者和反馈用户
```
