# DayScope

> 自动截图 + MiniMax AI 分析 + 时报/日报生成 · 后台无感运行

---

## 功能

- 🖼️ **每 2 分钟**自动截全屏（可配置）
- 🧠 每小时 **AI 分析**（MiniMax-VL-01）→ 自动生成 **时报**
- 📊 每天 **AI 汇总**（MiniMax-M3）→ 生成 **深度日报**
- 🔒 **隐私保护**：自动跳过密码管理器、银行 App 等敏感窗口
- 📁 输出到指定目录，按日期自动建文件夹
- 🔄 **systemd 守护**：开机自启 + 异常自动重启
- 🧹 自动清理过期原始截图（保留 7 天，报告永久）

---

## 文件结构

```
~/.dayscope/
├── config.yaml                  # 配置文件
├── tracker.py                   # 主程序
├── lib/                         # 模块
│   ├── screenshot.py            # 截图
│   ├── window.py                # 获取活动窗口
│   ├── privacy.py               # 隐私过滤
│   ├── analyzer.py              # AI 分析
│   └── reporter.py              # 报告生成
├── venv/                        # Python 虚拟环境
├── logs/                        # 日志
├── screenshots/                 # 原始截图（按天/小时分目录）
└── state/                       # 运行状态（幂等性）

~/WorkSpace/Document/汇报/日报/
└── 2026-06-13/
    ├── 时报-14.md
    ├── 时报-15.md
    └── 日报.md
```

---

## 快速开始

### 安装

```bash
bash ~/.dayscope/install.sh
```

会做这些事：
1. 检查依赖（gnome-screenshot, openclaw）
2. 创建 Python venv 并装依赖
3. 安装 systemd user service
4. 启用开机自启 + lingering（登出后继续运行）
5. 启动服务

### 常用命令

```bash
# 状态
systemctl --user status dayscope

# 实时日志
journalctl --user -u dayscope -f
tail -f ~/.dayscope/logs/tracker.log

# 停止 / 启动 / 重启
systemctl --user stop dayscope
systemctl --user start dayscope
systemctl --user restart dayscope

# 禁用（不想要开机自启时）
systemctl --user disable dayscope
```

### 调试模式

```bash
# 单次截图（不启动服务）
~/.dayscope/venv/bin/python ~/.dayscope/tracker.py --once-screenshot

# 分析指定小时（调试 AI prompt 用）
~/.dayscope/venv/bin/python ~/.dayscope/tracker.py --once-analyze 2026-06-13/14
```

---

## 配置 (`config.yaml`)

### 截图频率

```yaml
screenshot:
  interval_minutes: 2          # 改成 5 可以 5 分钟一次
  retention_days: 7            # 原始图保留天数，0=永不清
  skip_unchanged: true         # 屏幕没变就跳过
```

### 隐私黑名单

```yaml
privacy:
  enabled: true
  blacklist:
    - "1Password"
    - "银行"
    - "支付宝"
    # ... 加你自己的
```

> 检测的是**窗口标题**，所以要在 1Password 这种 App 里看到具体页面（标题栏含 "1Password"）才会跳过。

### AI 模型

```yaml
ai:
  model: "MiniMax-VL-01"        # vision 模型
  hourly_run_at_minute: 50     # 每小时第 50 分跑分析
  daily_run_at: "23:55"         # 每天几点几分出日报
```

### 报告输出

```yaml
reports:
  output_dir: "/home/mashuai/WorkSpace/Document/汇报/日报"
  date_folder_format: "%Y-%m-%d"
  hourly_filename: "时报-{hour:02d}.md"
  daily_filename: "日报.md"
```

---

## 故障排查

### 截图失败

1. **检查 gnome-screenshot**：`gnome-screenshot -f /tmp/test.png` 是否成功
2. **检查目录权限**：`ls -la ~/WorkSpace/Document/汇报/日报/`
3. **检查 systemd 环境变量**：service 文件里要有 `DISPLAY=:0` 和 `XAUTHORITY`

### AI 调用失败

1. **检查 openclaw**：`openclaw infer image describe --file test.png --prompt "看看"`
2. **查看日志**：`tail -f ~/.dayscope/logs/tracker.log`
3. **手动调试**：`~/.dayscope/venv/bin/python tracker.py --once-analyze 2026-06-13/14`

### Wayland 截图黑屏

Wayland 下需要授予 GNOME "屏幕录制" 权限：
- 设置 → 隐私 → 屏幕录制 → 开启 `gnome-screenshot`

### systemd service 不启动

```bash
# 看错误日志
journalctl --user -u dayscope -n 50

# 手动运行看错误
~/.dayscope/venv/bin/python ~/.dayscope/tracker.py
```

---

## 性能与成本

- 每小时 30 张截图，每张约 100-300KB JPEG
- 每天 720 张，约 70-200 MB
- AI 分析：每 2 小时约 30k tokens，本地模型 0 成本
- 磁盘：建议保留 7-30 天自动清理

---

## 二次开发

模块都是独立的，可以单独使用：

```python
from lib.screenshot import ScreenshotTaker
from lib.analyzer import AIAnalyzer
from lib.reporter import Reporter

t = ScreenshotTaker(Path("./screens"))
path = t.take()
print(f"截图: {path}")

a = AIAnalyzer()
result = a.analyze_hour(Path("./screens/2026-06-13/14"), prompt="...")
print(result)
```

---

## 已知限制

- **Wayland 多屏**：目前截全屏（合并所有显示器），多屏分辨率高时 AI 分析可能超时
- **依赖桌面会话**：登出后若没启用 lingering 服务会停
- **窗口标题权限**：Wayland 下获取窗口标题可能受限，会退化到不过滤
- **AI 误识别**：复杂场景识别可能不准确，建议人工校对关键产出

---

## 关键设计决策（踩过的坑）

### 1. 两步分析：视觉 → 文本归纳

AI 视觉模型逐图识别，文本模型跨图归纳：

```
60 张截图 → 60 个 event (vision) → 3-7 个任务 (text)
```

**为什么不是一步**：M3 视觉模型看不到“60 张图一样”这个事实，会逐图硬凑“在写代码”。文本模型能一眼看出“60 个 event 主题相同 → 1 个任务”

### 2. 挂机/空档识别（重要）

**问题**：60 张相同图，AI 默认全识为“在工作”

**修法**：prompt 必须明确三句：
1. 屏幕内容几乎一样 → 标 `category=挂机`
2. **不需证明他在工作**，看不到动作就是挂机
3. **60 张聊天页不间断 = 60 个挂机**（别被聊天页内容误导）

验证（17 点挂机场景）：弱 prompt 只识别 1/60，强 prompt 识别 54/60（95% 准确率）

### 3. 截图去重：不用 md5

**问题**：md5 hash 会因鼠标光标位置变动而不同 → 误判为“已变化” → 60 张相同图全保留

**修法**：PIL **像素采样**（5×5 = 25 点 + 缩到 64×64 灰度）生成 hash。鼠标小动不会改变采样点

### 4. Obsidian 渲染：不用 HTML

**问题**：`<details><summary>...</summary></details>` 在 Obsidian 被当代码块

**修法**：用 Obsidian 原生 callout 语法：
```markdown
> [!note] 标题
>
> 内容
```

### 5. service 环境变量

systemd service 跑后台时，**环境变量可能不包含 openclaw 路径**。修法：service 的 `[Service]` 段加：

```ini
Environment="PATH=%h/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin"
```

或 `install.sh` 中 `command -v openclaw` 找到路径后写入 service。

### 6. 名字变更成本

`截图-跟踪器` 改名为 `DayScope` 涉及：
- 目录 `~/.screenshot-tracker` → `~/.dayscope`
- service 单元名
- 扩展 uuid（**一旦 GNOME 加载过旧 uuid，需要用新 uuid 或重装扩展**）
- config 里所有路径

**一次性 sed 替换 + 重装扩展** 必重启用 systemd + 重新登入加载 GNOME。

---

最后更新：2026-06-14