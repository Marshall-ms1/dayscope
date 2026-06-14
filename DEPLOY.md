# DayScope · 跨机器部署指南

## 目标

在一台新装好的 Ubuntu/GNOME 机器上，**3 条命令**搞定整个截图 + AI 分析系统。

---

## 前置依赖（每台新机器只做一次）

### 1. 系统级包

```bash
sudo apt install -y python3-venv python3-gi python3-dbus \
                    libglib2.0-bin gnome-shell dbus
```

### 2. OpenClaw（用于 AI 分析）

```bash
# 按 OpenClaw 官方安装方式装好
# 配置好 minimax-cn 的 API key（去 openclaw 模型管理里设置，不要 commit 到 git）
openclaw configure --section model
# 或手填：~/.openclaw/agents/main/agent/openclaw-agent.sqlite
```

### 3. Git 远端仓库

把 `~/.dayscope/` 推到自己的 git：

```bash
cd ~/.dayscope
git init
cat > .gitignore << 'EOF'
venv/
screenshots/
logs/
state/
__pycache__/
*.pyc
EOF
git add -A
git commit -m "Initial commit"
git remote add origin git@your-git-host.com:mashuai/dayscope.git
git push -u origin main
```

---

## 新机器部署（3 条命令）

```bash
# 1. Clone 仓库
git clone git@your-git-host.com:mashuai/dayscope.git ~/.dayscope

# 2. 一键安装
cd ~/.dayscope
bash install.sh

# 3. 登出登入一次（让 mutter 加载截图扩展 screenshot-helper@local）
#   登出 → 重新登入
```

`install.sh` 会自动：

1. 装 Python venv + 依赖（APScheduler、Pillow、PyYAML、tzlocal）
2. 创建日志/截图/state 目录
3. 渲染 service 文件（替换 `$HOME` 和 user id）
4. 安装 systemd --user service
5. 启用 lingering（登出后继续运行）
6. 安装 GNOME 扩展到 `~/.local/share/gnome-shell/extensions/`
7. 启动服务

**部署完后**：

- 验证 service 跑着：`systemctl --user status dayscope`
- 验证扩展加载：`gnome-extensions info screenshot-helper@local`（状态应该是 ACTIVE）
- 验证 dbus 接口：`gdbus call --session --dest cn.local.ScreenshotHelper --object-path /cn/local/ScreenshotHelper --method cn.local.ScreenshotHelper.ListScreens`
- 等下一分钟看截图：`ls -la ~/.dayscope/screenshots/$(date +%Y-%m-%d)/$(date +%H)/`

---

## 升级（任何机器上）

```bash
cd ~/.dayscope
git pull
systemctl --user restart dayscope
```

---

## 关键设计

### 为什么用 template service 文件

`~/.dayscope/dayscope.service.template` 里用 `@USER_HOME@` 和 `@USER_ID@` 占位符，install.sh 渲染时替换为实际路径。这样仓库里的 service 文件可以跨用户/跨机器共享。

### 为什么 GNOME 扩展也进仓库

扩展的 JS 代码是 tracker 的"依赖"（没有它截图 dbus 接口就不可用）。所以放在 `~/.dayscope/extension/` 下，跟 git 走，install.sh 自动复制到 `~/.local/share/gnome-shell/extensions/`。

### 哪些东西不进 git（.gitignore）

| 项 | 原因 |
|---|---|
| `venv/` | 几百 MB，含平台特定 .so |
| `screenshots/` | 你屏幕上的隐私内容 |
| `logs/` | 含本地路径，跨机器无意义 |
| `state/` | 当日分析中间状态 |
| `__pycache__/` | Python 字节码 |

### 跨机器同步的边界

| 同步什么 | 方式 |
|---|---|
| 源码、配置、扩展 | git |
| 系统级包 | 文档里写好，新机器重装 |
| OpenClaw auth（API key） | **不**通过 git 同步，openclaw 自己的事 |
| 当日截图 / 日报 | **不**同步，本地看就行 |

---

## 故障排查

### 截图不工作

```bash
# 1. service 跑没
systemctl --user status dayscope

# 2. dbus 接口在不在
busctl --user list | grep cn.local
# 如果没出现，说明 GNOME 扩展没加载
gnome-extensions info screenshot-helper@local
# 状态是 ACTIVE 就 OK；不是 ACTIVE 就登出登入

# 3. 手动测一次截屏
gdbus call --session --dest cn.local.ScreenshotHelper --object-path /cn/local/ScreenshotHelper \
  --method cn.local.ScreenshotHelper.Screenshot --timeout 10 \
  false false "/tmp/test.png"
file /tmp/test.png
# 应该输出 PNG image data

# 4. 手动跑一次主程序（前台）
cd ~/.dayscope
./venv/bin/python tracker.py --once-screenshot
```

### AI 不工作

```bash
# 1. openclaw 通了没
openclaw models
# 至少能看到 minimax-cn/MiniMax-M3

# 2. 视觉模型能跑没
openclaw infer image describe-many --json \
  --file ~/.dayscope/screenshots/$(date +%Y-%m-%d)/$(date +%H)/$(ls -t ~/.dayscope/screenshots/$(date +%Y-%m-%d)/$(date +%H) | head -1) \
  --prompt "describe in 1 sentence" \
  --model minimax-cn/MiniMax-M3
```

### 重装 service

```bash
systemctl --user stop dayscope
rm ~/.config/systemd/user/dayscope.service
systemctl --user daemon-reload
cd ~/.dayscope && bash install.sh
```
