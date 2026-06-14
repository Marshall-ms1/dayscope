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

        # 2. 渲染甘特图（24 小时横向条带 + 任务彩色块）
        lines = ["## 今日进度（甘特图）", ""]
        # 顶部时间轴
        lines.append("```")
        lines.append("  00 02 04 06 08 10 12 14 16 18 20 22")
        lines.append("  ├──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┤")
        # 全天整体活跃度
        bar = ["  "]
        for h in range(24):
            r = hourly_results.get(h)
            if not r:
                ch = "·"
            else:
                events = r.get("events", [])
                if not events:
                    ch = "○"
                else:
                    idle = sum(1 for e in events if e.get("category") in ("挂机", "休息"))
                    idle_ratio = idle / len(events) if events else 0
                    if idle_ratio > 0.7:
                        ch = "▒"  # 大量挂机
                    elif idle_ratio > 0.3:
                        ch = "░"
                    else:
                        ch = "█"  # 活跃
            bar.append(ch)
        bar.append("  整体活跃度")
        lines.append("".join(bar))
        lines.append("```")
        lines.append("")

        # 3. 任务甘特条（主线 + 支线分组）
        main_tasks = [t for t in all_tasks if t["is_main"]]
        side_tasks = [t for t in all_tasks if not t["is_main"]]

        if main_tasks:
            lines.append("### 🟦 主线任务")
            lines.append("")
            for t in main_tasks:
                lines.append(self._render_gantt_row(t, indent="  "))
        if side_tasks:
            lines.append("")
            lines.append("### 🟨 支线/碎片")
            lines.append("")
            for t in side_tasks:
                lines.append(self._render_gantt_row(t, indent="  "))

        # 4. 进度统计
        done_hours = sum(1 for h in range(24) if hourly_results.get(h))
        total_productive_hours = sum(
            1 for h in range(24) if hourly_results.get(h)
            and any(e.get("category") not in ("挂机", "休息") for e in hourly_results[h].get("events", []))
        )
        lines += [
            "",
            f"**今日完成度**：{done_hours} / 24 小时有数据 · 有效产出 {total_productive_hours} 小时",
            "",
        ]
        return "\n".join(lines)

    def _render_gantt_row(self, task: dict, indent: str = "") -> str:
        """渲染单条甘特条：标题 + 24 字符宽的进度条

        优化：最少跨 1 小时（同小时任务也跨 sh 到 sh+1）
        """
        sh, eh = task["sh"], task["eh"]
        title = task["title"]
        cat = task["category"]
        hour_key = task["hour_key"]

        # 24 字符宽的条
        bar = ["·"] * 24
        if eh == sh:
            eh = sh + 1  # 最少跨 1 小时
        for h in range(sh, min(eh + 1, 24)):
            bar[h] = "█"
        bar_str = "".join(bar)

        # 标题截断
        max_title_len = 18
        if len(title) > max_title_len:
            title = title[:max_title_len - 1] + "…"

        return f"{indent}`{bar_str}` {title}  `{cat}`  `{int(hour_key):02d}:00`"

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
