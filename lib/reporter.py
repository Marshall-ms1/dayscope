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
        """写时报"""
        folder = self.date_folder(date)
        path = folder / self.hourly_tpl.format(hour=hour)

        events = result.get("events", [])
        summary = result.get("summary", "（无总结）")
        mode = result.get("mode", "混合")
        focus = result.get("focus_score", 0)
        productivity = result.get("productivity_score", 0)
        insights = result.get("insights", [])
        outputs = result.get("key_outputs", [])

        lines = [
            f"# 时报 · {date.strftime('%Y-%m-%d')} {hour:02d}:00 - {hour:02d}:59",
            "",
            f"> **本小时一句话**：{summary}",
            "",
            f"- **工作模式**：{mode}",
            f"- **专注度**：{focus:.2f} / 1.0",
            f"- **生产力**：{productivity:.2f} / 1.0",
            "",
            "## 活动时间线",
            "",
        ]

        if events:
            lines.append("| 时间 | 应用 | 类型 | 活动 |")
            lines.append("|------|------|------|------|")
            for e in events:
                start = e.get("start", "?")
                end = e.get("end", "?")
                app = e.get("app", "?")
                cat = e.get("category", "")
                activity = e.get("activity", "")
                details = e.get("details", "")
                line = f"| {start}-{end} | {app} | {cat} | {activity}"
                if details:
                    line += f"<br><sub>{details}</sub>"
                lines.append(line + " |")
        else:
            lines.append("_（无活动记录）_")

        if outputs:
            lines += ["", "## 关键产出", ""]
            for o in outputs:
                lines.append(f"- {o}")

        if insights:
            lines += ["", "## 洞察与建议", ""]
            for i, ins in enumerate(insights, 1):
                lines.append(f"{i}. {ins}")

        lines += [
            "",
            "---",
            f"_生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · AI 自动分析_",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        log.info("已写入时报: %s", path)
        return path

    def write_daily(self, date: datetime, daily_result: dict, hourly_results: dict):
        """写日报"""
        folder = self.date_folder(date)
        path = folder / self.daily_tpl

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