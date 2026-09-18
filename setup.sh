#!/usr/bin/env bash
# ==============================================================================
# Visium HD Single-Cell RNA Quantity QC Platform - One-Click Interactive Setup
# ==============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

print_banner() {
    clear 2>/dev/null || true
    echo -e "${CYAN}${BOLD}"
    echo "========================================================================"
    echo "       Visium HD Single-Cell RNA Quantity QC Web Platform Setup        "
    echo "          10x Genomics Space Ranger StarDist Integration               "
    echo "========================================================================"
    echo -e "${NC}"
}

print_banner

# ------------------------------------------------------------------------------
# Step 1: Hardware & System Resource Inspection
# ------------------------------------------------------------------------------
echo -e "${BLUE}${BOLD}[Step 1/5] 系统硬件与环境自检...${NC}"

OS_NAME="$(uname -s)"
ARCH="$(uname -m)"
TOTAL_CORES="$(grep -c ^processor /proc/cpuinfo 2>/dev/null || nproc 2>/dev/null || echo 1)"
TOTAL_MEM_KB="$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)"
TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))
DISK_AVAIL_GB="$(df -BG "$ROOT_DIR" | tail -1 | awk '{print $4}' | tr -d 'G')"

echo -e "  操作系统:     ${GREEN}${OS_NAME} (${ARCH})${NC}"
echo -e "  CPU 逻辑核心: ${GREEN}${TOTAL_CORES} 核心${NC}"
echo -e "  可用物理内存: ${GREEN}${TOTAL_MEM_GB} GB${NC}"
echo -e "  当前可用磁盘: ${GREEN}${DISK_AVAIL_GB} GB${NC}"

# Resource Advice
if [ "$TOTAL_MEM_GB" -lt 32 ]; then
    echo -e "  ${YELLOW}[建议] 检测到物理内存小于 32GB。Space Ranger 图像分割处理超大 WSI TIFF 切片建议具备 32GB 以上内存。${NC}"
else
    echo -e "  ${GREEN}[通过] 内存与计算资源充沛，满足 Space Ranger 深度学习模型推理需求。${NC}"
fi

echo ""

# ------------------------------------------------------------------------------
# Step 2: Python 3 Runtime & Dependency Installation
# ------------------------------------------------------------------------------
echo -e "${BLUE}${BOLD}[Step 2/5] Python 3 运行时与依赖库检测...${NC}"

PYTHON_BIN="$(which python3 2>/dev/null || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo -e "  ${RED}[错误] 未检测到 python3。请先使用包管理器安装 Python 3 (建议 >= 3.9):${NC}"
    echo "         Ubuntu/Debian: sudo apt update && sudo apt install -y python3 python3-pip"
    exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
echo -e "  Python 解析器: ${GREEN}${PYTHON_BIN} (v${PY_VERSION})${NC}"

# Check and install python packages
echo -e "  正在检测并安装平台与图像转码依赖 (fastapi, tifffile, openslide, opensdpc 等)..."
"$PYTHON_BIN" -m pip install -q --upgrade pip 2>/dev/null || true
"$PYTHON_BIN" -m pip install -q -r "$ROOT_DIR/requirements.txt" || {
    echo -e "  ${YELLOW}用户权限安装依赖...${NC}"
    "$PYTHON_BIN" -m pip install -q --user -r "$ROOT_DIR/requirements.txt"
}

echo -e "  ${GREEN}[通过] Web 服务端依赖库就绪。${NC}\n"

# ------------------------------------------------------------------------------
# Step 3: Space Ranger Detection & Guided Installation
# ------------------------------------------------------------------------------
echo -e "${BLUE}${BOLD}[Step 3/5] 10x Genomics Space Ranger 检测与安装...${NC}"

DETECTED_SR=""
if which spaceranger >/dev/null 2>&1; then
    DETECTED_SR="$(which spaceranger)"
elif [ -x "$HOME/software/10x/spaceranger-4.1.0/spaceranger" ]; then
    DETECTED_SR="$HOME/software/10x/spaceranger-4.1.0/spaceranger"
elif [ -x "$ROOT_DIR/spaceranger-4.1.0/spaceranger" ]; then
    DETECTED_SR="$ROOT_DIR/spaceranger-4.1.0/spaceranger"
fi

INSTALL_SR=true
if [ -n "$DETECTED_SR" ]; then
    SR_VER="$("$DETECTED_SR" --version 2>/dev/null | head -n 1 || echo '未知版本')"
    echo -e "  ${GREEN}[检测成功] 发现已就绪的 Space Ranger:${NC}"
    echo -e "             路径: ${BOLD}${DETECTED_SR}${NC}"
    echo -e "             版本: ${BOLD}${SR_VER}${NC}"
    echo ""
    read -r -p "  是否直接使用该现有 Space Ranger? [Y/n]: " USE_EXISTING
    USE_EXISTING="${USE_EXISTING:-Y}"
    if [[ "$USE_EXISTING" =~ ^[Yy]$ ]]; then
        INSTALL_SR=false
        export SPACERANGER_BIN="$DETECTED_SR"
    fi
fi

if [ "$INSTALL_SR" = true ]; then
    echo -e "\n  ${YELLOW}${BOLD}=== 10x Space Ranger 交互式安装向导 ===${NC}"
    echo -e "  由于 10x Genomics 官方许可协议（EULA）限制，Space Ranger 安装包需要用户在官网同意协议并生成下载链接。"
    echo -e "  1. 请用浏览器打开下载页面:"
    echo -e "     ${CYAN}${BOLD}https://www.10xgenomics.com/support/software/space-ranger/downloads${NC}"
    echo -e "  2. 填写简要信息并勾选同意协议，页面将立即生成专属于你的 curl 或 wget 下载命令。"
    echo ""

    read -r -p "  请输入安装目标目录路径 (默认: $HOME/software/10x): " TARGET_INSTALL_DIR
    TARGET_INSTALL_DIR="${TARGET_INSTALL_DIR:-$HOME/software/10x}"
    mkdir -p "$TARGET_INSTALL_DIR"

    echo ""
    echo -e "  请选择安装包提供方式:"
    echo "    [1] 粘贴官网生成的 curl / wget 命令或下载 URL"
    echo "    [2] 本地已存有下载好的 .tar.gz 安装包路径"
    read -r -p "  请选择 [1 或 2] (默认: 1): " PKG_MODE
    PKG_MODE="${PKG_MODE:-1}"

    TAR_FILE=""
    if [ "$PKG_MODE" = "2" ]; then
        while [ -z "$TAR_FILE" ] || [ ! -f "$TAR_FILE" ]; do
            read -r -p "  请输入 .tar.gz 压缩包的绝对路径: " TAR_FILE
            if [ ! -f "$TAR_FILE" ]; then
                echo -e "  ${RED}文件不存在，请重新输入!${NC}"
            fi
        done
    else
        echo -e "  请将官网生成的完整 curl / wget 命令或带 Token 的 URL 粘贴在下方并回车:"
        read -r -p "> " USER_INPUT_CMD

        # Extract URL from command if full curl or wget was pasted
        DOWNLOAD_URL=""
        if echo "$USER_INPUT_CMD" | grep -q "http"; then
            DOWNLOAD_URL=$(echo "$USER_INPUT_CMD" | grep -o -E 'https?://[^"'"'"' ]+' | head -1)
        else
            echo -e "  ${RED}未在输入中解析出有效 URL，请重新检查！${NC}"
            exit 1
        fi

        TAR_FILE="$TARGET_INSTALL_DIR/spaceranger-latest.tar.gz"
        echo -e "\n  ${CYAN}正在下载 Space Ranger 安装包到: $TAR_FILE ...${NC}"
        wget -c -O "$TAR_FILE" "$DOWNLOAD_URL" || curl -C - -o "$TAR_FILE" "$DOWNLOAD_URL"
    fi

    echo -e "\n  ${CYAN}正在解压 Space Ranger 安装包，请稍候...${NC}"
    tar -xzf "$TAR_FILE" -C "$TARGET_INSTALL_DIR"

    UNPACKED_BIN="$(find "$TARGET_INSTALL_DIR" -maxdepth 2 -name "spaceranger" -type f -perm /111 | head -1)"
    if [ -n "$UNPACKED_BIN" ]; then
        echo -e "  ${GREEN}[安装成功] Space Ranger 已部署在: ${UNPACKED_BIN}${NC}"
        export SPACERANGER_BIN="$UNPACKED_BIN"

        # Ask to add to bashrc
        read -r -p "  是否将 Space Ranger 自动加入 ~/.bashrc 环境变量? [Y/n]: " ADD_PATH
        ADD_PATH="${ADD_PATH:-Y}"
        if [[ "$ADD_PATH" =~ ^[Yy]$ ]]; then
            SR_DIR="$(dirname "$UNPACKED_BIN")"
            if ! grep -q "$SR_DIR" ~/.bashrc 2>/dev/null; then
                echo "export PATH=\"$SR_DIR:\$PATH\"" >> ~/.bashrc
                echo -e "  ${GREEN}已成功写入 ~/.bashrc${NC}"
            fi
        fi
    else
        echo -e "  ${RED}[错误] 未在解压目录中找到 spaceranger 可执行文件，请检查安装包。${NC}"
        exit 1
    fi
fi

echo ""

# ------------------------------------------------------------------------------
# Step 4: Web Port and Data Directory Configuration
# ------------------------------------------------------------------------------
echo -e "${BLUE}${BOLD}[Step 4/5] 服务端口与数据存储路径配置...${NC}"

DEFAULT_PORT=20100
read -r -p "  请输入 Web 服务监听端口 [默认: ${DEFAULT_PORT}]: " WEB_PORT
WEB_PORT="${WEB_PORT:-$DEFAULT_PORT}"

# Check port conflict
if ss -tuln | grep -q ":${WEB_PORT} "; then
    echo -e "  ${YELLOW}[提示] 检测到本地端口 ${WEB_PORT} 目前有服务占用。${NC}"
    read -r -p "  是否仍在此端口启动或覆盖? [Y/n]: " PORT_OVERRIDE
    PORT_OVERRIDE="${PORT_OVERRIDE:-Y}"
    if [[ ! "$PORT_OVERRIDE" =~ ^[Yy]$ ]]; then
        read -r -p "  请输入新的可用端口: " WEB_PORT
    fi
fi

# Configure Data Storage Directory
DEFAULT_DATA_DIR="$ROOT_DIR"
if [ -d "/mnt/ktdb2/yls/10x/visium_qc_app" ] && [ -w "/mnt/ktdb2/yls/10x/visium_qc_app" ]; then
    DEFAULT_DATA_DIR="/mnt/ktdb2/yls/10x/visium_qc_app"
fi
read -r -p "  请输入大文件上传与结果数据存储目录 [默认: ${DEFAULT_DATA_DIR}]: " USER_DATA_DIR
USER_DATA_DIR="${USER_DATA_DIR:-$DEFAULT_DATA_DIR}"
mkdir -p "$USER_DATA_DIR/uploads" "$USER_DATA_DIR/runs"

echo -e "  服务监听端口设定为: ${GREEN}${WEB_PORT}${NC}"
echo -e "  数据存储目录设定为: ${GREEN}${USER_DATA_DIR}${NC}\n"

# ------------------------------------------------------------------------------
# Step 5: Service Launch Mode
# ------------------------------------------------------------------------------
echo -e "${BLUE}${BOLD}[Step 5/5] 选择启动方式...${NC}"
echo "    [1] 直接前台启动运行 (推荐用于测试 / 终端实时查看日志)"
echo "    [2] 后台常驻守护进程启动 (nohup)"
echo "    [3] 注册为 Linux Systemd 用户级守护服务 (开机自启)"
read -r -p "  请选择 [1, 2, 3] (默认: 1): " RUN_MODE
RUN_MODE="${RUN_MODE:-1}"

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '127.0.0.1')"

print_access_urls() {
    echo ""
    echo -e "${GREEN}${BOLD}========================================================================${NC}"
    echo -e "${GREEN}${BOLD}        🎉 Visium HD 样本 RNA 含量评估质控系统已就绪！               ${NC}"
    echo -e "${GREEN}${BOLD}========================================================================${NC}"
    echo -e "  本地访问地址:   ${CYAN}${BOLD}http://127.0.0.1:${WEB_PORT}${NC}"
    echo -e "  局域网访问地址: ${CYAN}${BOLD}http://${LAN_IP}:${WEB_PORT}${NC}"
    echo ""
    echo -e "  提示: 若需外网访问，可使用您常用的反向代理工具（如 FRP / Nginx / Cloudflare Tunnel）"
    echo -e "        将本机的 ${BOLD}127.0.0.1:${WEB_PORT}${NC} 映射至您的域名或公网端口。"
    echo -e "${GREEN}${BOLD}========================================================================${NC}"
    echo ""
}

if [ "$RUN_MODE" = "2" ]; then
    echo -e "  正在后台启动服务..."
    DATA_DIR="$USER_DATA_DIR" PORT="$WEB_PORT" SPACERANGER_BIN="$SPACERANGER_BIN" nohup "$PYTHON_BIN" app.py --port "$WEB_PORT" --data-dir "$USER_DATA_DIR" > server.log 2>&1 &
    PID=$!
    echo -e "  ${GREEN}服务已在后台运行 (PID: $PID)，日志保存在 server.log${NC}"
    print_access_urls
elif [ "$RUN_MODE" = "3" ]; then
    SERVICE_FILE="$HOME/.config/systemd/user/visium-hd-qc.service"
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Visium HD Single-Cell RNA Quantity QC Platform (Port ${WEB_PORT})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${PYTHON_BIN} ${ROOT_DIR}/app.py --port ${WEB_PORT} --data-dir ${USER_DATA_DIR}
WorkingDirectory=${ROOT_DIR}
Restart=always
RestartSec=3
Environment=PORT=${WEB_PORT}
Environment=DATA_DIR=${USER_DATA_DIR}
Environment=SPACERANGER_BIN=${SPACERANGER_BIN}

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now visium-hd-qc.service
    echo -e "  ${GREEN}Systemd 用户守护服务已成功创建并启动！${NC}"
    print_access_urls
else
    print_access_urls
    echo -e "${YELLOW}正在前台启动服务，按 Ctrl+C 可停止运行...${NC}\n"
    DATA_DIR="$USER_DATA_DIR" PORT="$WEB_PORT" SPACERANGER_BIN="$SPACERANGER_BIN" exec "$PYTHON_BIN" app.py --port "$WEB_PORT" --data-dir "$USER_DATA_DIR"
fi
