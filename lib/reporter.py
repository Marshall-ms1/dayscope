"""报告生成：把 AI 分析结果写成 Markdown 时报/日报"""
import json
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)


class Reporter:
    def __init__(self, output_dir: str, date_format: str = "%Y-%m-%d",
                 hourly_tpl: str = "时报-{hour:02d}.md",
                 daily_tpl: str = "日报.md"):
        self.output_dir = Path(output_dir).expanduser()
        self.date_format = date_format
        self.hourly_tpl = hourly_tpl
        self.daily_tpl = daily_tpl

    def date_folder(self, date: datetime) -> Path:
        folder = self.output_dir / date.strftime(self.date_format)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_hourly(self, date: datetime, hour: int, result: dict):
        """写时报：任务驱动的结构"""
        folder = self.date_folder(date)
        path = folder / self.hourly_tpl.format(hour=hour)

        tasks = result.get("tasks", [])
        events = result.get("events", [])
        summary = result.get("summary", "（无总结）")
        mode = result.get("mode", "混合")
        focus = result.get("focus_score", 0)
        productivity = result.get("productivity_score", 0)
        insights = result.get("insights", [])

        lines = [
            "---",
            "cssclasses: ds-read-mode",
            "---",
            "",
            f"# 时报 · {date.strftime('%Y-%m-%d')} {hour:02d}:00 - {hour:02d}:59",
            "",
            f"> ## {summary}",
            "",
            f"- **工作模式**：{mode}",
            f"- **专注度**：{focus:.2f} / 1.0",
            f"- **生产力**：{productivity:.2f} / 1.0",
            f"- **任务数**：{len(tasks)} 个",
            "",
            "## 本小时做了什么",
            "",
        ]

        if tasks:
            # 任务汇总（主要看这里）
            for i, t in enumerate(tasks, 1):
                title = t.get("title", "（未命名任务）")
                cat = t.get("category", "")
                start = t.get("start", "?")
                end = t.get("end", "?")
                details = t.get("details", "")
                outcomes = t.get("outcomes", [])
                apps = t.get("apps", [])

                lines.append(f"### {i}. {title}  `{cat}`  `{start} - {end}`")
                if details:
                    lines.append(f"   {details}")
                if apps:
                    lines.append(f"   - **应用**: {', '.join(apps)}")
                if outcomes and outcomes != ["none"]:
                    pretty = ", ".join(o for o in outcomes if o != "none")
                    if pretty:
                        lines.append(f"   - **产出**: {pretty}")
                lines.append("")
        else:
            lines.append("_（未识别出任务，可能识别失败）_")
            lines.append("")

        # 原始事件（Obsidian 兼容的 callout 折叠块）
        if events:
            lines += [
                "> [!note] 原始事件（仅供查验）",
                "",
            ]
            lines.append("| 时间 | 应用 | 类型 | 活动 |")
            lines.append("|------|------|------|------|")
            for e in events:
                time = e.get("time", "?")
                app = e.get("app", "?")
                cat = e.get("category", "")
                activity = e.get("activity", "")
                details = e.get("details", "")
                line = f"| {time} | {app} | {cat} | {activity}"
                if details:
                    line += f" — {details}"
                lines.append(line + " |")
            lines.append("")

        if insights:
            lines += ["", "## 💡 洞察与建议", ""]
            for i, ins in enumerate(insights, 1):
                lines.append(f"{i}. {ins}")

        lines += [
            "",
            "---",
            f"_生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · AI 自动归纳_",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        log.info("已写入时报: %s", path)
        return path

    def write_daily(self, date: datetime, daily_result: dict, hourly_results: dict):
        """写日报（完整版，23:55 跑一次）"""
        folder = self.date_folder(date)
        path = folder / self.daily_tpl

        # 头部 + 甘特图（预先生成，最后会被 override 刷新）
        gantt_block = self._build_gantt_block(date, hourly_results, daily_result)

        headline = daily_result.get("headline", "（无标题）")
        core_work = daily_result.get("core_work", [])
        time_dist = daily_result.get("time_distribution", {})
        top_apps = daily_result.get("top_apps", [])
        key_outputs = daily_result.get("key_outputs", [])
        focus = daily_result.get("focus_score", 0)
        productivity = daily_result.get("productivity_score", 0)
        highlights = daily_result.get("highlights", [])
        lowlights = daily_result.get("lowlights", [])
        tomorrow = daily_result.get("tomorrow_suggestions", [])

        lines = [
            "---",
            "cssclasses: ds-read-mode",
            "---",
            "",
            f"# 日报 · {date.strftime('%Y-%m-%d')}",
            "",
            f"> ## {headline}",
            "",
            gantt_block,
            "",
            "## 今日核心",
            "",
        ]
        for c in core_work:
            lines.append(f"- {c}")

        # 时间分配
        lines += ["", "## 时间分配", ""]
        if time_dist:
            lines.append("| 类别 | 占比 |")
            lines.append("|------|------|")
            for k, v in sorted(time_dist.items(), key=lambda x: -x[1]):
                lines.append(f"| {k} | {v}% |")
            # 简易可视化
            lines += ["", "```", "时间分配图：" + "".join(
                f"\n{k:8s} {'█' * int(v/2)} {v}%" for k, v in time_dist.items()
            ), "```"]
        else:
            lines.append("_（无数据）_")

        # 工具使用
        lines += ["", "## 工具使用 Top 5", ""]
        if top_apps:
            lines.append("| 应用 | 占比 |")
            lines.append("|------|------|")
            for app, pct in top_apps[:5]:
                lines.append(f"| {app} | {pct}% |")
        else:
            lines.append("_（无数据）_")

        # 关键产出
        if key_outputs:
            lines += ["", "## 关键产出", ""]
            for o in key_outputs:
                lines.append(f"- {o}")

        # 效率指标
        lines += [
            "",
            "## 效率指标",
            "",
            f"- **专注度**：{focus:.2f} / 1.0",
            f"- **生产力**：{productivity:.2f} / 1.0",
        ]

        # 高光与低光
        if highlights:
            lines += ["", "## ✨ 高光时刻", ""]
            for h in highlights:
                lines.append(f"- {h}")
        if lowlights:
            lines += ["", "## ⚠️ 低效时段", ""]
            for h in lowlights:
                lines.append(f"- {h}")

        # 明日建议
        if tomorrow:
            lines += ["", "## 明日建议", ""]
            for s in tomorrow:
                lines.append(f"- {s}")

        # 时报汇总表（✓ = 有真实截图数据，⚠️ = 时报存在但 events 为空或可疑）
        # 同时把当天 0-23 小时里"没在 hourly_results 里出现"的也列出来
        all_hours = set(range(24))
        reported_hours = set(hourly_results.keys())
        missing_hours = sorted(all_hours - reported_hours)

        lines += [
            "",
            "## 时报汇总",
            "",
            "> ✓ = 有真实截图数据 · ⚠️ = 时报存在但 events 为空（数据可疑）· − = 无时报告",
            "",
            "| 时段 | 模式 | 专注度 | 生产力 | 一句话 |",
            "|------|------|--------|--------|--------|",
        ]
        for h in sorted(hourly_results.keys()):
            r = hourly_results[h]
            if not r:
                lines.append(f"| {h:02d}:00 | - | - | - | − 无数据 |")
                continue
            events = r.get("events", [])
            mark = "✓" if events else "⚠️"
            lines.append(
                f"| {h:02d}:00 {mark} | {r.get('mode','-')} | "
                f"{r.get('focus_score',0):.2f} | "
                f"{r.get('productivity_score',0):.2f} | "
                f"{r.get('summary','-')} |"
            )

        if missing_hours:
            lines += [
                "",
                f"**无时报告的时段**（共 {len(missing_hours)} 个）：{', '.join(f'{h:02d}:00' for h in missing_hours)}",
            ]

        lines += [
            "",
            "---",
            f"_生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · AI 自动分析_",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        log.info("已写入日报: %s", path)
        return path
    # =================== 甘特图 ===================
    def _build_gantt_block(self, date: datetime, hourly_results: dict, daily_result: dict = None) -> str:
        """生成今日甘特图块（markdown 表格 + 进度条）

        主线/支线区分：
        - 主线 = 出现 >= 3 次的任务主题，或 AI 在 core_work 里点名的
        - 支线 = 其他临时任务
        """
        # 1. 收集所有任务（按小时汇总）
        all_tasks = []  # [(start_hour, end_hour, title, category, is_main)]
        core_titles = []
        if daily_result:
            for cw in daily_result.get("core_work", []):
                # core_work 是字符串列表，不一定带项目名。直接用前 8 个字作为关键词
                core_titles.append(cw[:12])

        for h in sorted(hourly_results.keys()):
            r = hourly_results.get(h)
            if not r:
                continue
            # 解析 hour 为 int（key 可能是 "2026-06-14_10" 或 10）
            if isinstance(h, str) and "_" in h:
                h_int = int(h.split("_")[1])
            else:
                try:
                    h_int = int(h)
                except (ValueError, TypeError):
                    h_int = 0
            for t in r.get("tasks", []):
                title = t.get("title", "")
                start = t.get("start", "")
                end = t.get("end", "")
                cat = t.get("category", "碎片")
                # 解析 start/end 到 hour（保留分钟，跨小时的任务用跨小时表示）
                def _parse_time(s: str) -> int:
                    if not s or ":" not in s:
                        return -1
                    try:
                        h, m = s.split(":")[:2]
                        return int(h) * 60 + int(m)  # 转为分钟
                    except (ValueError, IndexError):
                        return -1
                sh_min = _parse_time(start)
                eh_min = _parse_time(end)
                if sh_min < 0:
                    sh_min = h_int * 60
                if eh_min < 0 or eh_min < sh_min:
                    eh_min = sh_min + 30  # 默认跨 30 分钟
                sh = sh_min // 60
                eh = eh_min // 60
                # 至少跨 1 小时显示（如果跨多小时肯定也跨）
                if eh == sh and eh_min - sh_min > 0:
                    eh = sh + 1  # 跨多小时
                # 主线判定：标题含 core_work 关键词 OR 在多个时报告出现 OR category 深度工作/调试
                is_main = False
                if cat in ("深度工作", "调试", "文档"):
                    is_main = True
                for kw in core_titles:
                    if kw and (kw in title or title in kw):
                        is_main = True
                        break
                all_tasks.append({
                    "sh": sh, "eh": max(eh, sh),
                    "title": title,
                    "category": cat,
                    "is_main": is_main,
                    "hour_key": h_int,
                })

        if not all_tasks:
            return "## 今日进度（甘特图）\n\n_暂无数据，等时报告陆续生成中..._"

        # 2. 计算活跃度（每个小时的挂机率）
        activity = {}
        for h in range(24):
            r = hourly_results.get(h) or hourly_results.get(f"{date.strftime('%Y-%m-%d')}_{h:02d}")
            if not r:
                activity[h] = 0  # 无数据
                continue
            events = r.get("events", [])
            if not events:
                activity[h] = 0
                continue
            idle = sum(1 for e in events if e.get("category") in ("挂机", "休息"))
            idle_ratio = idle / len(events) if events else 1
            activity[h] = 1 - idle_ratio  # 活跃度

        # 3. 拆主线/支线
        main_tasks = [t for t in all_tasks if t["is_main"]]
        side_tasks = [t for t in all_tasks if not t["is_main"]]

        # 4. 进度统计
        def _get_hour(h):
            return hourly_results.get(h) or hourly_results.get(f"{date.strftime('%Y-%m-%d')}_{h:02d}")
        done_hours = sum(1 for h in range(24) if _get_hour(h))
        total_productive_hours = sum(
            1 for h in range(24)
            if _get_hour(h)
            and any(e.get("category") not in ("挂机", "休息") for e in _get_hour(h).get("events", []))
        )

        # 5. 渲染 dataviewjs 块（CSS 美化甘特图）
        return self._render_dataviewjs_gantt(
            main_tasks, side_tasks, activity, done_hours, total_productive_hours
        )

    def _render_gantt_row(self, task: dict, indent: str = "") -> str:
        """保留旧接口（供其他场景使用），但已不被甘特图采用"""
        sh, eh = task["sh"], task["eh"]
        title = task["title"]
        cat = task["category"]
        hour_key = task["hour_key"]
        bar = ["·"] * 24
        if eh == sh:
            eh = sh + 1
        for h in range(sh, min(eh + 1, 24)):
            bar[h] = "█"
        bar_str = "".join(bar)
        max_title_len = 18
        if len(title) > max_title_len:
            title = title[:max_title_len - 1] + "…"
        return f"{indent}`{bar_str}` {title}  `{cat}`  `{int(hour_key):02d}:00`"

    def _render_dataviewjs_gantt(self, main_tasks, side_tasks, activity,
                                 done_hours, productive_hours) -> str:
        """渲染 dataviewjs 版甘特图（CSS 美化）

        Args:
            main_tasks: 主线任务列表
            side_tasks: 支线任务列表
            activity: {hour: 0-1} 活跃度
            done_hours: 今日有时报告的小时数
            productive_hours: 有效产出小时数
        """
        import json
        # JS 字符串转义：避免引号、反引号、${ 破坏 JS 语法
        tasks_for_js = {
            "main": [
                {
                    "sh": t["sh"], "eh": max(t["eh"], t["sh"] + 1),
                    "title": t["title"],
                    "category": t["category"],
                    "hour": t["hour_key"],
                }
                for t in main_tasks
            ],
            "side": [
                {
                    "sh": t["sh"], "eh": max(t["eh"], t["sh"] + 1),
                    "title": t["title"],
                    "category": t["category"],
                    "hour": t["hour_key"],
                }
                for t in side_tasks
            ],
            "activity": [round(activity.get(h, 0), 2) for h in range(24)],
            "stats": {
                "done": done_hours,
                "productive": productive_hours,
            }
        }
        # JSON 序列化后去掉 中文 里常见的特殊字符（避免冲突）
        tasks_json = json.dumps(tasks_for_js, ensure_ascii=False, separators=(",", ":"))

        # JS 代码块
        js_code = f'''```dataviewjs
// ===== DayScope 甘特图（由 dayscope 程序自动生成）=====
const DATA = {tasks_json};
const MAIN = DATA.main;
const SIDE = DATA.side;
const ACT = DATA.activity;

function catColor(cat) {{
  const map = {{
    "深度工作": "#4a90e2",
    "调试": "#7b68ee",
    "文档": "#5cb85c",
    "沟通": "#f5a623",
    "学习": "#9b59b6",
    "休息": "#95a5a6",
    "挂机": "#7f8c8d",
    "碎片": "#e67e22",
  }};
  return map[cat] || "#bdc3c7";
}}

function renderGroup(tasks, label, emoji) {{
  if (tasks.length === 0) return "";
  const rows = tasks.map(t => {{
    const left = (t.sh / 24 * 100);
    const width = ((t.eh - t.sh + 1) / 24 * 100);
    const color = catColor(t.category);
    return `<div class="ds-row">
  <div class="ds-time">${{String(t.hour).padStart(2,'0')}}:${{String(t.sh % 1 * 60 | 0).padStart(2,'0')}}</div>
  <div class="ds-bar-track">
    <div class="ds-bar" style="left:${{left}}%; width:${{width}}%; background:${{color}};" title="${{t.title}} · ${{t.category}} · ${{t.sh}}-${{t.eh}}时"></div>
  </div>
  <div class="ds-title">${{t.title}}</div>
  <div class="ds-cat" style="color:${{color}};">${{t.category}}</div>
</div>`;
  }}).join("");
  return `<div class="ds-group">
  <div class="ds-group-label">${{emoji}} ${{label}} <span class="ds-count">${{tasks.length}} 个</span></div>
  ${{rows}}
</div>`;
}}

// 活跃度轴：24 个小方块
const actBars = ACT.map((v, h) => {{
  const cls = v === 0 ? "ds-act-none" : (v > 0.6 ? "ds-act-high" : (v > 0.3 ? "ds-act-mid" : "ds-act-low"));
  return `<div class="${{cls}}" title="${{h}}时 · 活跃 ${{(v*100).toFixed(0)}}%"></div>`;
}}).join("");

const html = `
<style>
.ds-gantt {{
  font-family: var(--font-interface);
  font-size: 12px;
  margin: 8px 0 16px 0;
  padding: 12px;
  background: var(--background-primary);
  border-radius: 8px;
  border: 1px solid var(--background-modifier-border);
}}
.ds-axis {{
  display: flex;
  align-items: center;
  padding: 4px 0 8px 0;
  border-bottom: 1px solid var(--background-modifier-border);
  margin-bottom: 8px;
  color: var(--text-muted);
  font-family: var(--font-monospace);
}}
.ds-axis-time {{ width: 56px; flex-shrink: 0; }}
.ds-axis-bar {{ flex: 1; display: flex; justify-content: space-between; padding: 0 4px; }}
.ds-act-row {{
  display: flex;
  align-items: center;
  padding: 4px 0;
  margin-bottom: 12px;
  gap: 4px;
}}
.ds-act-label {{ width: 56px; flex-shrink: 0; color: var(--text-muted); font-size: 11px; }}
.ds-act-track {{ flex: 1; display: grid; grid-template-columns: repeat(24, 1fr); gap: 2px; }}
.ds-act-track > div {{
  height: 14px;
  border-radius: 2px;
  background: var(--background-secondary);
  transition: all 0.2s;
}}
.ds-act-track > div:hover {{ transform: scaleY(1.3); }}
.ds-act-none {{ background: var(--background-modifier-border) !important; opacity: 0.3; }}
.ds-act-low {{ background: linear-gradient(90deg, #e67e22 0%, #f5a623 100%) !important; opacity: 0.5; }}
.ds-act-mid {{ background: linear-gradient(90deg, #f5a623 0%, #f1c40f 100%) !important; opacity: 0.75; }}
.ds-act-high {{ background: linear-gradient(90deg, #5cb85c 0%, #4a90e2 100%) !important; }}
.ds-row {{
  display: flex;
  align-items: center;
  height: 24px;
  margin: 2px 0;
  transition: background 0.15s;
}}
.ds-row:hover {{ background: var(--background-modifier-hover); border-radius: 4px; }}
.ds-time {{ width: 56px; flex-shrink: 0; color: var(--text-muted); font-family: var(--font-monospace); font-size: 11px; padding-left: 4px; }}
.ds-bar-track {{
  flex: 1;
  height: 14px;
  background: var(--background-secondary);
  border-radius: 3px;
  position: relative;
  margin: 0 8px;
  overflow: hidden;
}}
.ds-bar {{
  position: absolute;
  height: 100%;
  border-radius: 3px;
  opacity: 0.85;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  transition: opacity 0.15s;
  cursor: pointer;
}}
.ds-bar:hover {{ opacity: 1; box-shadow: 0 2px 6px rgba(0,0,0,0.3); }}
.ds-title {{
  width: 220px;
  flex-shrink: 0;
  padding-left: 8px;
  color: var(--text-normal);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}}
.ds-cat {{
  width: 80px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 500;
}}
.ds-group {{ margin-bottom: 16px; }}
.ds-group-label {{
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text-normal);
  display: flex;
  align-items: center;
  gap: 8px;
}}
.ds-count {{
  font-size: 10px;
  color: var(--text-muted);
  background: var(--background-secondary);
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: normal;
}}
.ds-stats {{
  display: flex;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--background-modifier-border);
  font-size: 11px;
  color: var(--text-muted);
}}
.ds-stats span {{ padding: 2px 8px; background: var(--background-secondary); border-radius: 4px; }}
</style>

<div class="ds-gantt">
  <div class="ds-axis">
    <div class="ds-axis-time">活跃度</div>
    <div class="ds-axis-bar">
      <span>00</span><span>04</span><span>08</span><span>12</span><span>16</span><span>20</span><span>24</span>
    </div>
  </div>
  <div class="ds-act-row">
    <div class="ds-act-label">24h</div>
    <div class="ds-act-track">${{actBars}}</div>
  </div>
  ${{renderGroup(MAIN, "主线任务", "🟦")}}
  ${{renderGroup(SIDE, "支线/碎片", "🟨")}}
  <div class="ds-stats">
    <span>📶 时报覆盖 ${{DATA.stats.done}}/24h</span>
    <span>⚡ 有效产出 ${{DATA.stats.productive}}h</span>
    <span>🟦 ${{MAIN.length}} 主线</span>
    <span>🟨 ${{SIDE.length}} 支线</span>
  </div>
</div>
`;

dv.container.innerHTML = html;
```'''
        return "## 今日进度（甘特图）\n\n" + js_code + "\n"

    def update_daily_gantt(self, date: datetime, hourly_results: dict, daily_result: dict = None):
        """每小时更新日报的甘特图块（不动 AI 总结部分）

        策略：如果日报文件不存在 → 创建一个只含甘特图的占位文件
             如果存在 → 替换 ## 今日进度（甘特图） 块
        """
        folder = self.date_folder(date)
        path = folder / self.daily_tpl

        gantt_block = self._build_gantt_block(date, hourly_results, daily_result)

        if not path.exists():
            # 创建占位日报（含头部 + 甘特图 + 提示）
            placeholder = [
                f"# 日报 · {date.strftime('%Y-%m-%d')}",
                "",
                f"> ## 今日日报（生成中... {datetime.now().strftime('%H:%M')}）",
                "",
                gantt_block,
                "",
                "---",
                "",
                "_日报正文字段（headline / 核心 / 时间分配 / 建议）将在 23:55 跑 AI 总结后填充_",
                "",
            ]
            path.write_text("\n".join(placeholder), encoding="utf-8")
            log.info("创建占位日报（仅甘特图）: %s", path)
            return path

        # 已存在：替换 ## 今日进度（甘特图） 到 --- 之前的所有内容（除开 headline）
        text = path.read_text(encoding="utf-8")
        import re
        # 匹配 "## 今日进度（甘特图）" 开始到 "## 今日核心" 之前
        pattern = re.compile(
            r"## 今日进度（甘特图）.*?(?=^## 今日核心|\Z)",
            re.DOTALL | re.MULTILINE
        )
        if pattern.search(text):
            new_text = pattern.sub(gantt_block, text, count=1)
            path.write_text(new_text, encoding="utf-8")
            log.info("已刷新日报甘特图: %s", path)
        else:
            # 旧版日报没甘特图块，插在 headline 之后
            new_text = re.sub(
                r"(> ## [^\n]+\n\n)",
                r"\1\n" + gantt_block + "\n\n",
                text,
                count=1
            )
            path.write_text(new_text, encoding="utf-8")
            log.info("插入日报甘特图块: %s", path)
        return path

    # =================== 年度日历看板 ===================
    def write_calendar_overview(self, year: int = None) -> Path:
        """生成年度日历看板（dataviewjs 实现 + 点击跳转到日报）

        文件路径：output_dir/📅日历.md（放在所有日期文件夹的外侧）
        每天颜色 = 活跃小时数（绿色深浅梯度）
        点击格子 → 跳到当日日报
        """
        import json
        from datetime import date, timedelta
        from calendar import monthrange

        if year is None:
            year = datetime.now().year

        # 1. 聚合每年每天的活跃数据
        daily = self._aggregate_year_daily(year)

        # 2. 构建 365 天数据
        days = []
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        cur = start
        while cur <= end:
            d_str = cur.strftime("%Y-%m-%d")
            d = daily.get(d_str, {})
            days.append({
                "date": d_str,
                "active": d.get("active_hours", 0),
                "focus": round(d.get("avg_focus", 0), 2),
                "events": d.get("total_events", 0),
                "hourly": d.get("hourly", [0.0] * 24),  # 24 小时活跃度
            })
            cur += timedelta(days=1)

        # 3. 月度统计
        monthly = {}
        for d in days:
            m = d["date"][:7]
            if m not in monthly:
                monthly[m] = {"active": 0, "focus_sum": 0, "days": 0, "events": 0}
            monthly[m]["active"] += d["active"]
            monthly[m]["focus_sum"] += d["focus"]
            monthly[m]["events"] += d["events"]
            monthly[m]["days"] += 1
        months = []
        for m in sorted(monthly.keys()):
            s = monthly[m]
            avg_f = s["focus_sum"] / s["days"] if s["days"] > 0 else 0
            months.append({
                "month": m,
                "active": s["active"],
                "avg_focus": round(avg_f, 2),
                "events": s["events"],
            })

        # 4. 渲染 dataviewjs 块
        days_json = json.dumps(days, ensure_ascii=False, separators=(",", ":"))
        months_json = json.dumps(months, ensure_ascii=False, separators=(",", ":"))

        js_template = '''```dataviewjs
// ===== DayScope 年度日历看板（程序自动生成）=====
const DAYS = __DAYS__;
const MONTHS = __MONTHS__;
const YEAR = __YEAR__;

// 全局跳转函数：使用 Obsidian app API 跳转到日报
window.__openDaily = function(dateStr) {
  const dateOnly = `${dateStr}/日报.md`;          // 例如: 2026-06-14/日报.md
  const fullPath = `汇报/日报/${dateOnly}`;        // vault 内完整路径
  try {
    if (typeof app !== "undefined" && app.workspace) {
      // 1) 尝试 vault 完整路径
      let file = app.vault.getAbstractFileByPath(fullPath);
      if (!file) {
        // 2) 退而尝试 vault 根相对路径
        file = app.vault.getAbstractFileByPath(dateOnly);
      }
      // 3) 最后扫 vault.getFiles() 找含 dateStr 的日报.md
      if (!file) {
        const all = app.vault.getFiles();
        file = all.find(f =>
          f.name === "日报.md" && f.path.includes("/" + dateStr + "/")
        );
      }
      if (file) {
        app.workspace.openLinkText(file.path, "", false);
        return;
      } else {
        new Notice(`📅 ${dateStr} 还没有日报（该日无数据）`, 3000);
        return;
      }
    }
  } catch (e) {
    console.error("DayScope openDaily error:", e);
  }
  // 降级：使用 obsidian:// 协议
  window.location.href = `obsidian://open?path=${encodeURIComponent(fullPath)}`;
};

function dayColor(d) {
  // 6 档：有数据但全挂机（浅蓝）→ 活跃小时梯度（绿色）
  if (!d || d.events === 0) return "#ebedf0";
  if (d.active === 0)         return "#c5d4f0";
  if (d.active < 1)           return "#9be9a8";
  if (d.active < 3)           return "#40c463";
  if (d.active < 6)           return "#30a14e";
  return "#216e39";
}
function dayLabel(d) {
  if (!d || d.events === 0) return "无数据";
  if (d.active === 0)         return "有数据（挂机）";
  if (d.active < 1)           return "<1h 活跃";
  if (d.active < 3)           return "1-3h 活跃";
  if (d.active < 6)           return "3-6h 活跃";
  return "6h+ 活跃";
}
function hourColor(act) {
  if (act === 0)  return "#ebedf0";
  if (act < 0.05) return "#c5d4f0";
  if (act < 0.2)  return "#9be9a8";
  if (act < 0.5)  return "#40c463";
  if (act < 0.8)  return "#30a14e";
  return "#216e39";
}
function pad2(n) { return String(n).padStart(2, "0"); }

// 渲染一个月的格子
function renderMonth(monthStr) {
  const [y, m] = monthStr.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const last  = new Date(y, m, 0);
  const daysInMonth = last.getDate();
  const startWeekday = first.getDay();
  const monthDays = DAYS.filter(d => d.date.startsWith(monthStr));
  const offset = (startWeekday + 6) % 7;
  let cells = "";
  for (let i = 0; i < offset; i++) {
    cells += `<div class="ds-cell empty"></div>`;
  }
  for (let i = 0; i < daysInMonth; i++) {
    const dd = monthDays[i] || { date: `${monthStr}-${pad2(i+1)}`, active: 0, focus: 0, events: 0 };
    const color = dayColor(dd);
    const title = `${dd.date} · ${dayLabel(dd)} · 专注度 ${(dd.focus*100).toFixed(0)}% · ${dd.events} 事件`;
    cells += `<div class="ds-cell"
                 data-date="${dd.date}"
                 onclick="__openDaily('${dd.date}')"
                 style="background:${color};"
                 title="${title}"></div>`;
  }
  return `<div class="ds-month" data-month="${monthStr}">
    <div class="ds-month-name" onclick="window.__toggleMd('${monthStr}', this)" style="cursor:pointer;">
      <span class="ds-month-toggle">▸</span> ${m}月
    </div>
    <div class="ds-month-grid">${cells}</div>
  </div>`;
}

// 渲染月度详情（30 天 × 24 小时热力图）
function renderMonthDetail(monthStr) {
  const monthDays = DAYS.filter(d => d.date.startsWith(monthStr));
  if (monthDays.length === 0) {
    return `<div class="ds-md-empty">${monthStr} 暂无数据</div>`;
  }
  // 表头：24 小时
  let header = `<div class="ds-md-row ds-md-header-row">
    <div class="ds-md-date"></div>
    <div class="ds-md-cells">`;
  for (let h = 0; h < 24; h++) {
    header += `<div class="ds-md-hour-label" data-h="${h}">${h % 3 === 0 ? h : ""}</div>`;
  }
  header += `</div></div>`;

  // 行：每天
  let rows = "";
  for (const d of monthDays) {
    const dayNum = d.date.slice(8);
    let cellsHtml = "";
    for (let h = 0; h < 24; h++) {
      const act = (d.hourly && d.hourly[h]) || 0;
      const color = hourColor(act);
      const title = `${d.date} ${pad2(h)}:00 · 活跃度 ${(act*100).toFixed(0)}%`;
      cellsHtml += `<div class="ds-md-cell"
                       data-date="${d.date}"
                       onclick="__openDaily('${d.date}')"
                       style="background:${color};"
                       title="${title}"></div>`;
    }
    rows += `<div class="ds-md-row">
      <div class="ds-md-date">${dayNum}</div>
      <div class="ds-md-cells">${cellsHtml}</div>
    </div>`;
  }

  return `<div class="ds-md-wrap">
    <div class="ds-md-title">📊 ${monthStr} · 每日 24 小时活跃度（点击格子跳转到日报）</div>
    ${header}
    ${rows}
  </div>`;
}

const monthNames = ["一","二","三","四","五","六","七","八","九","十","十一","十二"];
const monthBlocks = monthNames.map((n, i) => renderMonth(`${YEAR}-${pad2(i+1)}`)).join("");

const monthStatsHtml = MONTHS.map(m => {
  const focusPct = (m.avg_focus*100).toFixed(0);
  return `<div class="ds-mstat">
    <div class="ds-mstat-name">${m.month}</div>
    <div class="ds-mstat-active">⚡ ${m.active}h</div>
    <div class="ds-mstat-focus">🎯 ${focusPct}%</div>
    <div class="ds-mstat-events">📊 ${m.events}</div>
  </div>`;
}).join("");

const totalActive = MONTHS.reduce((a,b) => a+b.active, 0);
const totalDays = DAYS.filter(d => d.events > 0).length;
const yearAvgFocus = MONTHS.length > 0
  ? (MONTHS.reduce((a,b)=>a+b.avg_focus,0) / MONTHS.length * 100).toFixed(0)
  : 0;

// 全局 toggle 函数
window.__toggleMd = function(monthStr, btn) {
  const wrap = document.getElementById(`ds-md-${monthStr}`);
  if (wrap) {
    wrap.remove();
    btn.querySelector(".ds-month-toggle").textContent = "▸";
    return;
  }
  const month = btn.closest(".ds-month");
  const detail = document.createElement("div");
  detail.id = `ds-md-${monthStr}`;
  detail.className = "ds-md-detail";
  detail.innerHTML = renderMonthDetail(monthStr);
  month.parentElement.insertBefore(detail, month.nextSibling);
  btn.querySelector(".ds-month-toggle").textContent = "▾";
};

const html = `
<style>
.ds-cal {
  font-family: var(--font-interface);
  font-size: 12px;
  padding: 20px;
  background: var(--background-primary);
  border-radius: 12px;
  border: 1px solid var(--background-modifier-border);
  max-width: 920px;
}
.ds-cal-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}
.ds-cal-title { font-size: 20px; font-weight: 700; color: var(--text-normal); }
.ds-cal-summary { font-size: 12px; color: var(--text-muted); display: flex; gap: 16px; }
.ds-cal-summary span strong { color: var(--text-accent); font-weight: 600; margin-left: 4px; }
.ds-months { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px 24px; margin-bottom: 20px; }
.ds-month { display: flex; flex-direction: column; gap: 4px; }
.ds-month-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 4px;
  user-select: none;
  padding: 2px 4px;
  border-radius: 4px;
  transition: background 0.15s;
}
.ds-month-name:hover { background: var(--background-modifier-hover); color: var(--text-normal); }
.ds-month-toggle { font-size: 10px; margin-right: 4px; }
.ds-month-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }
.ds-cell {
  aspect-ratio: 1;
  border-radius: 3px;
  background: #ebedf0;
  cursor: pointer;
  transition: all 0.15s ease;
  display: block;
  text-decoration: none;
  border: 1px solid rgba(0,0,0,0.05);
}
.ds-cell:hover {
  transform: scale(1.5);
  box-shadow: 0 3px 8px rgba(0,0,0,0.25);
  z-index: 10;
  position: relative;
  border-color: rgba(0,0,0,0.2);
}
.ds-cell.empty { background: transparent !important; border: none !important; pointer-events: none; }
.ds-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
  padding: 12px 0;
  border-top: 1px solid var(--background-modifier-border);
  margin-top: 8px;
  flex-wrap: wrap;
}
.ds-legend-cell { width: 14px; height: 14px; border-radius: 3px; display: inline-block; border: 1px solid rgba(0,0,0,0.05); }
.ds-mstats { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--background-modifier-border); }
.ds-mstat { padding: 10px 6px; background: var(--background-secondary); border-radius: 6px; text-align: center; transition: transform 0.15s; }
.ds-mstat:hover { transform: translateY(-2px); }
.ds-mstat-name { font-weight: 600; color: var(--text-normal); font-size: 12px; margin-bottom: 4px; }
.ds-mstat-active { font-size: 13px; color: #30a14e; font-weight: 600; margin-bottom: 2px; }
.ds-mstat-focus { font-size: 11px; color: var(--text-muted); margin-bottom: 2px; }
.ds-mstat-events { font-size: 10px; color: var(--text-faint, var(--text-muted)); }

/* ====== 月度详情（30 天 × 24 小时） ====== */
.ds-md-detail {
  grid-column: 1 / -1;
  margin-top: 8px;
  padding: 16px;
  background: var(--background-secondary);
  border-radius: 8px;
  border: 1px solid var(--background-modifier-border);
  animation: dsMdSlide 0.2s ease-out;
}
@keyframes dsMdSlide {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.ds-md-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}
.ds-md-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-normal);
  margin-bottom: 12px;
}
.ds-md-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ds-md-header-row { margin-bottom: 4px; }
.ds-md-row {
  display: flex;
  align-items: center;
  gap: 2px;
  height: 18px;
}
.ds-md-date {
  width: 28px;
  flex-shrink: 0;
  text-align: right;
  padding-right: 6px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-monospace);
}
.ds-md-cells {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 2px;
}
.ds-md-hour-label {
  font-size: 9px;
  color: var(--text-muted);
  text-align: center;
  font-family: var(--font-monospace);
  min-width: 0;
}
.ds-md-cell {
  aspect-ratio: 1;
  border-radius: 2px;
  background: #ebedf0;
  cursor: pointer;
  transition: all 0.12s ease;
  display: block;
  text-decoration: none;
  border: 1px solid rgba(0,0,0,0.04);
  height: 14px;
}
.ds-md-cell:hover {
  transform: scale(1.8);
  box-shadow: 0 2px 6px rgba(0,0,0,0.3);
  z-index: 10;
  position: relative;
  border-color: rgba(0,0,0,0.2);
}
</style>

<div class="ds-cal">
  <div class="ds-cal-header">
    <div class="ds-cal-title">📅 ${YEAR} 年活跃度看板</div>
    <div class="ds-cal-summary">
      <span>有数据 <strong>${totalDays}</strong> 天</span>
      <span>总活跃 <strong>${totalActive}h</strong></span>
      <span>年均专注 <strong>${yearAvgFocus}%</strong></span>
    </div>
  </div>
  <div class="ds-months">${monthBlocks}</div>
  <div class="ds-legend">
    <span>活跃度：</span>
    <span class="ds-legend-cell" style="background:#ebedf0"></span> 无数据
    <span class="ds-legend-cell" style="background:#c5d4f0"></span> 有数据（挂机）
    <span class="ds-legend-cell" style="background:#9be9a8"></span> &lt;1h
    <span class="ds-legend-cell" style="background:#40c463"></span> 1-3h
    <span class="ds-legend-cell" style="background:#30a14e"></span> 3-6h
    <span class="ds-legend-cell" style="background:#216e39"></span> 6h+
    <span style="margin-left:auto;">💡 悬停查看详情 · 点击格子跳转日报 · 点击月份展开 30 天 × 24h 热力图</span>
  </div>
  <div class="ds-mstats">${monthStatsHtml}</div>
</div>
`;

dv.container.innerHTML = html;
```'''
        js_code = js_template
        js_code = js_code.replace("__DAYS__", days_json)
        js_code = js_code.replace("__MONTHS__", months_json)
        js_code = js_code.replace("__YEAR__", str(year))

        # 5. 写文件
        path = self.output_dir / f"📅日历-{year}.md"
        # Python 侧也计算总览（用于文件末尾文字）
        total_active = sum(m["active"] for m in months)
        total_days = sum(1 for d in days if d["events"] > 0)
        header = (
            "---\n"
            "cssclasses: ds-read-mode\n"
            "---\n\n"
            f"# 📅 DayScope 日历看板 · {year}\n\n"
            f"> 自动统计每日活跃度 · 点击单元格查看日报详情\n\n"
            f"{js_code}\n\n"
            f"_最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 共 {total_active} 小时 · 覆盖 {total_days} 天_\n"
        )
        path.write_text(header, encoding="utf-8")
        log.info("已写入年度日历看板: %s", path)
        return path

    def _aggregate_year_daily(self, year: int) -> dict:
        """从 state/hourly_results.json 聚合年度每天数据"""
        from pathlib import Path
        import json as _json

        # state 文件路径
        state_path = Path(__file__).parent.parent / "state" / "hourly_results.json"
        if not state_path.exists():
            return {}

        try:
            with open(state_path) as f:
                all_results = _json.load(f)
        except Exception as e:
            log.warning("读 hourly_results.json 失败: %s", e)
            return {}

        # 第一遍：收集所有有数据的 (date, hour) 组合
        day_hour = {}  # {date_str: {hour: activity}}
        year_str = str(year)
        for key, result in all_results.items():
            if "_" not in key:
                continue
            # key 格式: 2026-06-14_10
            parts = key.rsplit("_", 1)
            if len(parts) != 2:
                continue
            date_str, hour_str = parts
            if not date_str.startswith(year_str):
                continue
            try:
                hour = int(hour_str)
            except (ValueError, TypeError):
                continue

            events = result.get("events", [])
            if not events:
                continue

            idle = sum(1 for e in events if e.get("category") in ("挂机", "休息"))
            idle_ratio = idle / len(events)
            activity = 1 - idle_ratio

            if date_str not in day_hour:
                day_hour[date_str] = {}
            day_hour[date_str][hour] = {
                "activity": activity,
                "events": len(events),
            }

        # 第二遍：按天聚合
        daily = {}
        for date_str, hours in day_hour.items():
            hourly = [0.0] * 24
            active_hours = 0
            total_events = 0
            focus_sum = 0.0
            for h in range(24):
                h_data = hours.get(h)
                if h_data:
                    hourly[h] = round(h_data["activity"], 2)
                    total_events += h_data["events"]
                    focus_sum += h_data["activity"]
                    if h_data["activity"] > 0.1:
                        active_hours += 1
            daily[date_str] = {
                "active_hours": active_hours,
                "total_hours": len(hours),
                "focus_sum": focus_sum,
                "total_events": total_events,
                "hourly": hourly,  # 24 小时活跃度（用于月度展开）
            }

        # 算日均 focus
        for d in daily.values():
            if d["total_hours"] > 0:
                d["avg_focus"] = d["focus_sum"] / d["total_hours"]
            else:
                d["avg_focus"] = 0

        return daily
