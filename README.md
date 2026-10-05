# 获取广东电信 IPTV 播放列表 + EPG 面板。
- **单 Rust 二进制**，内置 RTSP/UDP 代理，无需 rtp2httpd。

| 服务 | 地址 |
|---|---|
| 面板 | `http://<host>:4022/` |
| 播放列表 | `http://<host>:4022/playlist` |
| EPG | `http://<host>:4022/xmltv` |

---

## 一、前置条件

- **IPTV 账号必须由机顶盒注册**。光猫 / 路由器注册的账号用不了。
- 需要 **已绑定机顶盒的真实 MAC 和账号密码**。
- 主机需能跑 Linux 二进制（amd64 / arm64），且**与机顶盒同网段**，能收 IGMP 组播。
- 需要 rtp2httpd？**不需要**，本项目内置代理。

**准备信息**：

| 项 | 从哪获取 |
|---|---|
| IPTV 账号 (UserID) | 机顶盒设置 / 运营商合同 |
| IPTV 密码 | 同上 |
| 机顶盒 MAC | 机顶盒背面标签 |
| FCC 服务器地址 | [中国各地区 FCC 汇总](https://rtp2httpd.com/reference/cn-fcc-collection) |

---

## 二、安装

### 方式 A：一键脚本（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/oyz6/gd-iptv-panel/main/install.sh | sudo bash
```

管理：

```bash
sudo ./install.sh upgrade     # 升级
sudo ./install.sh restart     # 重启
sudo ./install.sh logs        # 实时日志
sudo ./install.sh uninstall   # 卸载
```

脚本自动处理：下载、SHA256 校验、systemd 服务、升级失败回滚。

### 方式 B：手动 systemd

```bash
# 1. 下载
wget https://github.com/oyz6/gd-iptv-panel/releases/latest/download/gd-iptv-panel-linux-amd64
chmod +x gd-iptv-panel-linux-amd64

# 2. 安装
sudo install -m 755 gd-iptv-panel-linux-amd64 /usr/local/bin/gd-iptv-panel
sudo mkdir -p /etc/gd-iptv-panel

# 3. 创建服务
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

# 4. 启动
sudo systemctl daemon-reload
sudo systemctl enable --now gd-iptv-panel
```

### 方式 C：Docker

```bash
docker run -d \
  --name gd-iptv-panel \
  --network host \
  --restart unless-stopped \
  -e TZ=Asia/Shanghai \
  -v /root/gd-iptv-panel/data:/data \
  ghcr.io/oyz6/gd-iptv-panel:latest
```

或 `docker-compose.yml`：

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
      - RUST_LOG=info,actix_http=warn
    volumes:
      - ./data:/data
```

---

## 三、首次配置

浏览器打开 `http://<主机IP>:4022/`，默认账号 `admin` / `admin`。

面板填写清单：

| 卡片 | 内容 | 必填 |
|---|---|---|
| ① 面板登录 | 改掉默认账号密码 | 建议 |
| ② IPTV 账号认证 | UserID / 密码 / 机顶盒 MAC | **必填** |
| ③ 内置代理 | FCC 服务器 / UDP 代理 / RTSP 代理 | **必填** |
| ④ 输出选项 | 播放列表 / EPG / 图标 / 置顶副本 | 建议全勾 |
| ⑤ 外部 M3U 源 | 合并第三方 M3U（按需） | 可选 |

**代理方式**：

| 场景 | 勾选 |
|---|---|
| 直播 | UDP 组播代理（走 `/rtp/`，速度快） |
| 回看 | RTSP 代理 + 生成时移回看 |

**FCC 服务器**：填 `IP:端口`，常见：

- `8027` — 华为平台
- `15970` — 中兴 / 烽火平台

---

## 四、播放器导入

```
http://<主机IP>:4022/playlist
```

EPG 会自动从 M3U 里读取（`x-tvg-url` 属性）。

- VLC：媒体 → 打开网络串流
- PotPlayer：打开 → 打开链接
- TiviMate：设置 → 播放列表 → 添加 M3U

---

## 五、频道规则

### 分组顺序

```
置顶 → 央视 → 广东 → 卫视 → 少儿 → CGTN → 超清4K → 其他
```

### 置顶频道

1. 广东珠江
2. 岭南戏曲
3. 大湾区卫视
4. 广东卫视
5. 广东4K
6. CCTV-11

**复制一份到列表顶部，原分组保留**。

### 央视排序

按 CCTV 数字顺序：`CCTV-1` ~ `CCTV-17`

- `CCTV-4K` 紧跟 `CCTV-4` 后
- `CCTV-5+` 紧跟 `CCTV-5` 后
- 央视特色频道（世界地理、怀旧剧场等）排最后

### 多线路合并

同一频道的多个画质版本合并为一个频道，输出多个 URL：

```m3u
#EXTINF:-1 tvg-name="CCTV-1" group-title="央视",CCTV-1
http://<host>:4022/rtp/...超清源
http://<host>:4022/rtp/...高清源
http://<host>:4022/rtp/...标清源
```

播放器按顺序尝试，第一个能播的就用。

### 显示名清洗

| 原始名 | 显示名 |
|---|---|
| `广东4K超高清 窄色域 30` | `广东4K` |
| `CCTV-5超清` / `CCTV-5体育` | `CCTV-5` |
| `CCTV5＋体育高清-测试` | `CCTV-5+` |
| `CCTV4K-25P` | `CCTV-4K` |
| `CCTV-3综艺` | `CCTV-3` |

---

## 六、配置文件

路径：

- systemd：`/etc/gd-iptv-panel/config.json`
- Docker：`./data/config.json`

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
    "playseek_template": "${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}",
    "fcc_server": "",
    "fcc_type": "telecom"
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

改端口：

```bash
sudo vi /etc/gd-iptv-panel/config.json
# "bind": "0.0.0.0:9000"
sudo systemctl restart gd-iptv-panel
```

---

## 七、命令行参数

```
Usage: gd-iptv-panel [OPTIONS]

  -c, --config <CONFIG>    配置文件路径 [default: ./config.json]
  -b, --bind <BIND>        监听地址（覆盖配置文件）
  -h, --help               显示帮助
  -V, --version            显示版本
```

---

## 八、API

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| GET | `/` | ❌ | Web 面板 |
| POST | `/api/login` | ❌ | 登录 |
| POST | `/api/logout` | ✅ | 登出 |
| GET | `/api/auth-check` | ❌ | 校验 token |
| GET | `/api/config` | ✅ | 读配置 |
| POST | `/api/config` | ✅ | 写配置 |
| GET | `/api/status` | ✅ | 状态 |
| GET | `/playlist` | ❌ | M3U |
| GET | `/xmltv` | ❌ | EPG |
| GET | `/logo/{id}.png` | ❌ | 图标 |
| GET | `/rtsp/{path}` | ❌ | RTSP 代理 |
| GET | `/rtp/{addr}` | ❌ | UDP 代理 |

需要认证的接口加请求头 `X-Auth-Token: <token>`。

```bash
TOKEN=$(curl -s -X POST http://localhost:4022/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' | jq -r .token)

curl -s http://localhost:4022/api/config -H "X-Auth-Token: $TOKEN" | jq
```

---

## 九、常用命令

### systemd

```bash
sudo systemctl restart gd-iptv-panel
sudo systemctl status gd-iptv-panel
sudo journalctl -u gd-iptv-panel -f
```

### Docker

```bash
docker compose ps
docker compose logs -f
docker compose restart
docker compose up -d --build      # 更新
docker compose down
```

---

## 十、升级

```bash
# 一键脚本
sudo ./install.sh upgrade

# systemd 手动
wget https://github.com/oyz6/gd-iptv-panel/releases/latest/download/gd-iptv-panel-linux-amd64
sudo systemctl stop gd-iptv-panel
sudo install -m 755 gd-iptv-panel-linux-amd64 /usr/local/bin/gd-iptv-panel
sudo systemctl start gd-iptv-panel

# Docker
docker compose pull
docker compose up -d
```

配置文件不会被覆盖。

---

## 十一、常见问题

**认证失败**：MAC 必须与机顶盒一致；光猫注册的账号用不了。

**端口 4022 被占用**：`ss -tlnp | grep 4022` 查，或改 `bind`。

**面板打不开**：检查服务状态；放行防火墙（`sudo ufw allow 4022`）。

**日志刷 `invalid HTTP version`**：无害，是端口扫描。默认已隐藏。

**复制按钮没反应**：HTTP 环境禁用剪贴板 API，点地址框手动 Ctrl+C。

**播放器打不开流**：检查播放器能否访问 `rtp2httpd_url` 里的 IP。

**回看不能用**：勾选 RTSP 代理 + 生成时移回看。

**FCC 不生效**：换当地 FCC 地址（参考上方链接）。

---

## 十二、源码构建

```bash
git clone https://github.com/oyz6/gd-iptv-panel.git
cd gd-iptv-panel

# 编译
cargo build --release --features rustls
./target/release/gd-iptv-panel

# 测试
cargo test merge

# 交叉编译 musl
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl --features rustls
```

---

## 十三、项目结构

```
gd-iptv-panel/
├── .github/workflows/release.yml
├── Cargo.toml
├── Cargo.lock
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .gitignore
├── install.sh
├── config.example.json
├── README.md
├── src/
│   ├── main.rs          路由入口
│   ├── config.rs        配置模型
│   ├── auth.rs          Token 认证
│   ├── iptv.rs          运营商认证 + 拉频道/EPG
│   ├── proxy.rs         RTSP / UDP 代理
│   ├── group.rs         分组 / 置顶
│   ├── merge.rs         相似频道合并 + 画质识别
│   ├── external.rs      外部源
│   └── m3u.rs           M3U / XMLTV 生成
├── static/index.html    前端面板
└── data/                运行时数据
    └── config.json
```

---

## 十四、许可

仅供个人学习研究使用，请遵守当地法律法规和运营商服务条款。
