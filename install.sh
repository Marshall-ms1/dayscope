#!/bin/bash
# DayScope 一键安装脚本
# 用法：bash install.sh
#
# 这个脚本要能跑在「新电脑」上（路径 / 用户都不同），所以全部路径都用 $HOME。
# 跑完后会自动:
#   1. 准备 Python venv + 装 Python 依赖
#   2. 创建必要的目录
#   3. 渲染 service 文件（替换 $HOME 和 user id）
#   4. 安装 systemd --user service
#   5. 安装 GNOME 扩展 dayscope-helper@local（如果还没装）
#   6. 启动服务
#   7. 提示用户：登出登入一次（让 mutter 加载扩展）

set -e

INSTALL_DIR="$HOME/.dayscope"
SERVICE_NAME="dayscope"
SERVICE_TEMPLATE="$INSTALL_DIR/${SERVICE_NAME}.service.template"
SERVICE_RENDERED="$INSTALL_DIR/${SERVICE_NAME}.service"
SYSTEMD_DIR="$HOME/.config/systemd/user"
EXT_UUID="dayscope-helper@local"
EXT_SRC_DIR="$INSTALL_DIR/extension"
EXT_DST_DIR="$HOME/.local/share/gnome-shell/extensions/${EXT_UUID}"

echo "==> 1. 检查系统级依赖"
MISSING_DEPS=()
command -v python3 >/dev/null || MISSING_DEPS+=("python3")
command -v systemctl >/dev/null || MISSING_DEPS+=("systemd")
command -v gdbus >/dev/null || MISSING_DEPS+=("gdbus (libglib2.0-bin)")
dpkg -l python3-gi >/dev/null 2>&1 || MISSING_DEPS+=("python3-gi")
dpkg -l python3-dbus >/dev/null 2>&1 || MISSING_DEPS+=("python3-dbus")
dpkg -l gnome-shell >/dev/null 2>&1 || MISSING_DEPS+=("gnome-shell")
command -v openclaw >/dev/null || echo "    ⚠️  openclaw 没找到（不影响安装，但 AI 分析会失败）"

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "❌ 缺少系统依赖：${MISSING_DEPS[*]}"
    echo "   请运行：sudo apt install -y python3-venv python3-gi python3-dbus libglib2.0-bin gnome-shell"
    exit 1
fi

echo "==> 2. 准备 Python 虚拟环境"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "==> 3. 创建目录"
mkdir -p "$INSTALL_DIR"/{logs,screenshots,state,lib}
mkdir -p "$HOME/WorkSpace/Document/汇报/日报"

echo "==> 4. 渲染 service 文件（替换 \$HOME、user id、openclaw 路径）"
USER_ID=$(id -u)
# Detect openclaw location (nvm / pip --user / 自装都找)
OPENCLAW_PATHS=""
for path in "$HOME/.nvm/current/bin" \
            "$HOME/.nvm/versions/node"/*/"bin" \
            "$HOME/.local/bin" \
            "$HOME/bin" \
            "/usr/local/bin" \
            "/opt/openclaw/bin"; do
    if [ -x "$path/openclaw" ]; then
        OPENCLAW_PATHS="$OPENCLAW_PATHS:$path"
    fi
done
# 去前导冒号
OPENCLAW_PATHS="${OPENCLAW_PATHS#:}"
if [ -z "$OPENCLAW_PATHS" ]; then
    echo "    ⚠️  找不到 openclaw 命令（AI 分析会失败，但截图还能跑）"
    OPENCLAW_PATHS="/usr/local/bin"
fi
echo "    openclaw 路径：$OPENCLAW_PATHS"
sed -e "s|@USER_HOME@|$HOME|g" \
    -e "s|@USER_ID@|$USER_ID|g" \
    -e "s|@OPENCLAW_PATHS@|$OPENCLAW_PATHS|g" \
    "$SERVICE_TEMPLATE" > "$SERVICE_RENDERED"

echo "==> 5. 安装 systemd user service"
mkdir -p "$SYSTEMD_DIR"
cp "$SERVICE_RENDERED" "$SYSTEMD_DIR/${SERVICE_NAME}.service"
systemctl --user daemon-reload

echo "==> 6. 启用开机自启（启用 lingering 让登出后继续运行）"
if command -v loginctl >/dev/null; then
    if loginctl enable-linger "$USER" 2>/dev/null; then
        echo "    ✅ lingering 已启用（登出后服务不会停）"
    else
        echo "    ⚠️  无法启用 lingering（需要 sudo），登出后服务会停"
    fi
fi

echo "==> 7. 安装 GNOME 扩展 dayscope-helper@local"
if [ -d "$EXT_SRC_DIR" ]; then
    mkdir -p "$EXT_DST_DIR"
    cp -r "$EXT_SRC_DIR"/* "$EXT_DST_DIR"/
    echo "    ✅ 扩展已复制到 $EXT_DST_DIR"
    if [ -f "$HOME/.local/share/gnome-shell/extensions/${EXT_UUID}/metadata.json" ]; then
        gnome-extensions enable "$EXT_UUID" 2>/dev/null || \
            echo "    ⚠️  无法立即 enable（可能需要先登出登入一次）"
    fi
else
    echo "    ⚠️  $EXT_SRC_DIR 不存在，跳过扩展安装"
    echo "       提示：扩展在另一台机器上需要重新装（从源码仓库拷过来）"
fi

echo "==> 8. 启动服务"
systemctl --user enable --now "${SERVICE_NAME}.service" 2>/dev/null || \
    systemctl --user start "${SERVICE_NAME}.service"

sleep 2
echo ""
echo "==> 服务状态："
systemctl --user status "${SERVICE_NAME}.service" --no-pager -l || true
echo ""
echo "==> 实时日志："
echo "    journalctl --user -u ${SERVICE_NAME} -f"
echo "    tail -f $INSTALL_DIR/logs/tracker.log"
echo ""
echo "==> 常用命令："
echo "    停止：   systemctl --user stop ${SERVICE_NAME}"
echo "    启动：   systemctl --user start ${SERVICE_NAME}"
echo "    重启：   systemctl --user restart ${SERVICE_NAME}"
echo "    状态：   systemctl --user status ${SERVICE_NAME}"
echo "    禁用：   systemctl --user disable ${SERVICE_NAME}"
echo ""
echo "==> ⚠️  重要：如果扩展 dayscope-helper@local 之前没装过，需要"
echo "    **登出一次再登入**（让 mutter 扫描并加载扩展）"
echo ""
echo "==> 调试模式（不安装服务）："
echo "    $INSTALL_DIR/venv/bin/python $INSTALL_DIR/tracker.py --once-screenshot"
echo "    $INSTALL_DIR/venv/bin/python $INSTALL_DIR/tracker.py --once-analyze 2026-06-13/14"
echo ""
echo "✅ 安装完成！截图会每 1 分钟触发一次，时报在每小时 50 分生成，日报在每天 23:55。"
