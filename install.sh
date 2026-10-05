#!/usr/bin/env bash
#
# gd-iptv-panel 安装 / 升级 / 管理脚本
#
# 用法:
#   ./install.sh            安装（若已存在则升级）
#   ./install.sh install    安装
#   ./install.sh upgrade    升级到最新版本
#   ./install.sh uninstall  卸载
#   ./install.sh restart    重启服务
#   ./install.sh status     查看状态
#   ./install.sh logs       查看实时日志
#   ./install.sh version    查看当前版本
#

set -e

# =========================
# 配置
# =========================
REPO="oyz6/gd-iptv-panel"
BIN_NAME="gd-iptv-panel"
INSTALL_PATH="/usr/local/bin/${BIN_NAME}"
CONFIG_DIR="/etc/${BIN_NAME}"
CONFIG_FILE="${CONFIG_DIR}/config.json"
SERVICE_NAME="${BIN_NAME}.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"

# =========================
# 颜色
# =========================
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; NC=''
fi

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[FAIL]${NC} $*" >&2; }
title() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}"; }

# =========================
# 工具函数
# =========================

# 检查 root
need_root() {
    if [ "$(id -u)" -ne 0 ]; then
        err "此操作需要 root 权限，请用 sudo 运行"
        exit 1
    fi
}

# 检查命令是否存在
has_cmd() { command -v "$1" >/dev/null 2>&1; }

# 检测系统架构
detect_arch() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64|amd64)
            echo "amd64"
            ;;
        aarch64|arm64)
            echo "arm64"
            ;;
        *)
            err "不支持的架构：$arch"
            err "目前仅支持 x86_64 和 aarch64"
            exit 1
            ;;
    esac
}

# 检测是否需要 sudo（下载/解压用）
download_file() {
    local url="$1"
    local dest="$2"

    if has_cmd wget; then
        wget -q --show-progress -O "$dest" "$url"
    elif has_cmd curl; then
        curl -fL --progress-bar -o "$dest" "$url"
    else
        err "需要 wget 或 curl 才能下载"
        exit 1
    fi
}

# 获取最新版本 tag
get_latest_version() {
    local url="https://api.github.com/repos/${REPO}/releases/latest"
    if has_cmd curl; then
        curl -fsSL "$url" | grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/'
    elif has_cmd wget; then
        wget -qO- "$url" | grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/'
    else
        echo ""
    fi
}

# 从 config.json 里读端口
get_port() {
    if [ -f "$CONFIG_FILE" ]; then
        grep -oP '"bind"\s*:\s*"[^"]*:\K[0-9]+' "$CONFIG_FILE" 2>/dev/null | head -1 || echo "4022"
    else
        echo "4022"
    fi
}

# =========================
# 下载二进制
# =========================
download_binary() {
    local arch="$1"
    local tag="$2"
    local out="$3"

    local file="gd-iptv-panel-linux-${arch}"
    local url
    if [ -n "$tag" ]; then
        url="https://github.com/${REPO}/releases/download/${tag}/${file}"
        info "下载版本 ${tag}"
    else
        url="https://github.com/${REPO}/releases/latest/download/${file}"
        info "下载最新版本"
    fi
    info "URL: $url"

    download_file "$url" "$out" || {
        err "下载失败"
        exit 1
    }

    if [ ! -s "$out" ]; then
        err "下载的文件为空"
        exit 1
    fi
    chmod +x "$out"
    ok "下载完成：$(ls -lh "$out" | awk '{print $5}')"
}

# 校验 SHA256（可选，失败不中断）
verify_sha256() {
    local arch="$1"
    local tag="$2"
    local binfile="$3"

    local file="gd-iptv-panel-linux-${arch}.sha256"
    local url
    if [ -n "$tag" ]; then
        url="https://github.com/${REPO}/releases/download/${tag}/${file}"
    else
        url="https://github.com/${REPO}/releases/latest/download/${file}"
    fi

    local tmp_sha
    tmp_sha=$(mktemp)
    if download_file "$url" "$tmp_sha" 2>/dev/null; then
        local expected
        expected=$(awk '{print $1}' "$tmp_sha")
        local actual
        actual=$(sha256sum "$binfile" | awk '{print $1}')
        if [ "$expected" = "$actual" ]; then
            ok "SHA256 校验通过"
        else
            warn "SHA256 校验失败（可能是网络问题或文件损坏）"
            warn "  expected: $expected"
            warn "  actual:   $actual"
        fi
    fi
    rm -f "$tmp_sha"
}

# =========================
# 创建 systemd 服务
# =========================
create_service() {
    info "创建 systemd 服务：$SERVICE_FILE"

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=gd-iptv-panel
Documentation=https://github.com/${REPO}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${INSTALL_PATH} -c ${CONFIG_FILE}
Restart=on-failure
RestartSec=5
Environment=RUST_LOG=info,actix_http=warn

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
    ok "服务已创建并启用"
}

# =========================
# 停止已有服务/进程
# =========================
stop_existing() {
    # 停止 systemd 服务
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "停止已有服务"
        systemctl stop "$SERVICE_NAME"
    fi

    # 杀掉残留进程
    if pgrep -x "$BIN_NAME" >/dev/null 2>&1; then
        info "清理残留进程"
        pkill -x "$BIN_NAME" || true
        sleep 1
    fi
}

# =========================
# 检查端口占用
# =========================
check_port() {
    local port="$1"
    if ! has_cmd ss; then
        return 0
    fi

    local pid
    pid=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | head -1)
    if [ -n "$pid" ]; then
        local name
        name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        if [ "$name" != "$BIN_NAME" ]; then
            warn "端口 ${port} 已被进程 ${pid} (${name}) 占用"
            warn "如启动失败，请手动处理：sudo kill ${pid}"
        fi
    fi
}

# =========================
# 显示访问信息
# =========================
show_info() {
    local port
    port=$(get_port)
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$ip" ] && ip=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')

    echo ""
    echo -e "${BOLD}${GREEN}========================================${NC}"
    echo -e "${BOLD}${GREEN}   安装完成！${NC}"
    echo -e "${BOLD}${GREEN}========================================${NC}"
    echo ""
    echo -e "  ${BOLD}面板地址${NC}:  http://${ip}:${port}/"
    echo -e "  ${BOLD}默认账号${NC}:  admin"
    echo -e "  ${BOLD}默认密码${NC}:  admin"
    echo ""
    echo -e "  ${BOLD}播放列表${NC}:  http://${ip}:${port}/playlist"
    echo -e "  ${BOLD}EPG${NC}     :  http://${ip}:${port}/xmltv"
    echo ""
    echo -e "  ${BOLD}配置文件${NC}:  ${CONFIG_FILE}"
    echo -e "  ${BOLD}查看日志${NC}:  sudo journalctl -u ${SERVICE_NAME} -f"
    echo -e "  ${BOLD}重启服务${NC}:  sudo systemctl restart ${SERVICE_NAME}"
    echo ""
    echo -e "${YELLOW}提示：首次登录后请立即修改默认密码！${NC}"
    echo ""
}

# =========================
# 安装
# =========================
cmd_install() {
    need_root
    title "安装 gd-iptv-panel"

    # 检查系统
    if ! has_cmd systemctl; then
        err "需要 systemd 环境（大多数现代 Linux 都支持）"
        exit 1
    fi

    local arch
    arch=$(detect_arch)
    info "检测到架构：${arch}"

    # 如果是升级，保留配置
    local is_upgrade=0
    if [ -f "$CONFIG_FILE" ]; then
        is_upgrade=1
        info "检测到已存在的配置：${CONFIG_FILE}（将保留）"
    fi

    # 下载到临时文件
    local tmp_bin
    tmp_bin=$(mktemp)
    trap "rm -f $tmp_bin" EXIT

    download_binary "$arch" "" "$tmp_bin"
    verify_sha256 "$arch" "" "$tmp_bin"

    # 停止已有服务
    stop_existing

    # 安装二进制
    info "安装到：$INSTALL_PATH"
    install -m 755 "$tmp_bin" "$INSTALL_PATH"
    ok "二进制已安装"

    # 创建配置目录
    mkdir -p "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR"

    # 首次安装时初始化配置文件
    if [ ! -f "$CONFIG_FILE" ]; then
        info "初始化默认配置文件"
        # 二进制启动时会自动生成，我们这里先创建空目录
        # 让服务首次启动时生成配置
        ok "配置文件将在服务首次启动时生成"
    else
        ok "保留已有配置文件"
    fi

    # 检查端口
    local port
    port=$(get_port)
    check_port "$port"

    # 创建/更新服务
    create_service

    # 启动服务
    info "启动服务"
    systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "服务已启动"
    else
        err "服务启动失败，查看日志："
        journalctl -u "$SERVICE_NAME" -n 30 --no-pager
        exit 1
    fi

    if [ "$is_upgrade" -eq 1 ]; then
        title "升级完成"
    else
        show_info
    fi
}

# =========================
# 升级
# =========================
cmd_upgrade() {
    need_root
    title "升级 gd-iptv-panel"

    if [ ! -f "$INSTALL_PATH" ]; then
        err "尚未安装，请先运行：$0 install"
        exit 1
    fi

    # 记录旧版本
    local old_ver
    old_ver=$("$INSTALL_PATH" --version 2>/dev/null | head -1 || echo "unknown")
    info "当前版本：${old_ver}"

    local arch
    arch=$(detect_arch)

    local tmp_bin
    tmp_bin=$(mktemp)
    trap "rm -f $tmp_bin" EXIT

    download_binary "$arch" "" "$tmp_bin"
    verify_sha256 "$arch" "" "$tmp_bin"

    # 备份旧版本
    local bak="${INSTALL_PATH}.bak"
    info "备份旧版本到：$bak"
    cp "$INSTALL_PATH" "$bak"

    # 停止服务
    stop_existing

    # 替换二进制
    install -m 755 "$tmp_bin" "$INSTALL_PATH"
    ok "二进制已更新"

    # 启动
    systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        local new_ver
        new_ver=$("$INSTALL_PATH" --version 2>/dev/null | head -1 || echo "unknown")
        ok "升级成功：${old_ver} → ${new_ver}"
        echo ""
        echo -e "  备份文件：${bak}（如需回滚，覆盖回 $INSTALL_PATH 即可）"
    else
        err "升级后启动失败，正在回滚..."
        cp "$bak" "$INSTALL_PATH"
        systemctl restart "$SERVICE_NAME"
        err "已回滚到旧版本，请检查日志："
        journalctl -u "$SERVICE_NAME" -n 30 --no-pager
        exit 1
    fi
}

# =========================
# 卸载
# =========================
cmd_uninstall() {
    need_root
    title "卸载 gd-iptv-panel"

    read -rp "确认卸载？将删除服务、二进制和配置 [y/N]: " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        info "已取消"
        exit 0
    fi

    # 停止并禁用服务
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "停止服务"
        systemctl stop "$SERVICE_NAME"
    fi
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "禁用开机自启"
        systemctl disable "$SERVICE_NAME" >/dev/null 2>&1
    fi

    # 删除服务文件
    if [ -f "$SERVICE_FILE" ]; then
        info "删除服务文件"
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
    fi

    # 删除二进制
    if [ -f "$INSTALL_PATH" ]; then
        info "删除二进制"
        rm -f "$INSTALL_PATH"
    fi
    rm -f "${INSTALL_PATH}.bak"

    # 询问是否删除配置
    if [ -d "$CONFIG_DIR" ]; then
        read -rp "是否删除配置目录 ${CONFIG_DIR}？[y/N]: " rm_cfg
        if [[ "$rm_cfg" =~ ^[Yy]$ ]]; then
            rm -rf "$CONFIG_DIR"
            ok "配置目录已删除"
        else
            info "配置保留在：${CONFIG_DIR}"
        fi
    fi

    ok "卸载完成"
}

# =========================
# 重启 / 状态 / 日志 / 版本
# =========================
cmd_restart() {
    need_root
    if ! systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        err "服务未运行"
        exit 1
    fi
    systemctl restart "$SERVICE_NAME"
    sleep 1
    systemctl status "$SERVICE_NAME" --no-pager -l | head -15
}

cmd_status() {
    if ! systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}"; then
        err "未安装"
        exit 1
    fi
    systemctl status "$SERVICE_NAME" --no-pager -l
}

cmd_logs() {
    if ! systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}"; then
        err "未安装"
        exit 1
    fi
    journalctl -u "$SERVICE_NAME" -f
}

cmd_version() {
    if [ ! -f "$INSTALL_PATH" ]; then
        err "未安装"
        exit 1
    fi
    echo "已安装版本："
    "$INSTALL_PATH" --version 2>/dev/null || echo "unknown"

    local latest
    latest=$(get_latest_version)
    if [ -n "$latest" ]; then
        echo "最新版本：  ${latest}"
    fi
}

# =========================
# 帮助
# =========================
show_help() {
    cat <<EOF
${BOLD}gd-iptv-panel 安装脚本${NC}

用法:
  $0 [命令]

命令:
  install     安装（默认命令，已安装则升级）
  upgrade     升级到最新版本
  uninstall   卸载
  restart     重启服务
  status      查看运行状态
  logs        查看实时日志（Ctrl+C 退出）
  version     查看已安装和最新版本
  help        显示此帮助

示例:
  sudo $0              # 安装或升级
  sudo $0 upgrade      # 升级到最新版本
  sudo $0 logs         # 查看实时日志
  sudo $0 uninstall    # 卸载

默认路径:
  二进制    ${INSTALL_PATH}
  配置      ${CONFIG_FILE}
  服务      ${SERVICE_FILE}

仓库: https://github.com/${REPO}
EOF
}

# =========================
# 主入口
# =========================
main() {
    local cmd="${1:-install}"

    case "$cmd" in
        install)         cmd_install ;;
        upgrade|update)  cmd_upgrade ;;
        uninstall|remove)cmd_uninstall ;;
        restart)         cmd_restart ;;
        status)          cmd_status ;;
        logs|log)        cmd_logs ;;
        version|-v|--version) cmd_version ;;
        help|-h|--help)  show_help ;;
        *)
            err "未知命令：$cmd"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
