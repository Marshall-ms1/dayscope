#!/usr/bin/env python3
"""
DayScope 主程序
- 每 N 分钟截全屏
- 每小时 50 分用 MiniMax-VL-01 分析生成时报
- 每天 23:55 汇总当日 24 个时报告生成日报

后台 daemon，通过 systemd --user 启动
"""
import os
import sys
import json
import signal
import logging
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# 让 lib 可导入
sys.path.insert(0, str(Path(__file__).parent))
from lib.screenshot import ScreenshotTaker
from lib.privacy import PrivacyGuard
from lib.analyzer import AIAnalyzer
from lib.reporter import Reporter

CONFIG_PATH = Path(__file__).parent / "config.yaml"
STATE_DIR = Path(__file__).parent / "state"


def setup_logging(cfg: dict):
    log_cfg = cfg.get("logging", {})
    log_file = Path(log_cfg.get("file", "")).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_cfg.get("level", "INFO")))
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # 文件 handler（轮转）
    fh = RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get("max_bytes", 10485760),
        backupCount=log_cfg.get("backup_count", 5),
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


def load_state(name: str) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{name}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(name: str, data: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Tracker:
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.log = setup_logging(self.config)
        self.log.info("=" * 60)
        self.log.info("DayScope 启动 @ %s", datetime.now().isoformat())

        # 模块初始化
        sc = self.config["screenshot"]
        self.screenshot = ScreenshotTaker(
            output_dir=Path(sc["output_dir"]).expanduser(),
            jpeg_quality=sc.get("jpeg_quality", 70),
            max_dimension=sc.get("max_dimension", 1920),
        )

        pv = self.config.get("privacy", {})
        self.privacy = PrivacyGuard(
            enabled=pv.get("enabled", False),
            blacklist=pv.get("blacklist", []),
        )

        ai = self.config["ai"]
        self.analyzer = AIAnalyzer(
            model=ai.get("model", "MiniMax-VL-01"),
            max_images_per_call=ai.get("max_images_per_call", 18),
            timeout_seconds=ai.get("timeout_seconds", 300),
        )

        rp = self.config["reports"]
        self.reporter = Reporter(
            output_dir=rp["output_dir"],
            date_format=rp.get("date_folder_format", "%Y-%m-%d"),
            hourly_tpl=rp.get("hourly_filename", "时报-{hour:02d}.md"),
            daily_tpl=rp.get("daily_filename", "日报.md"),
        )

        self.skip_unchanged = sc.get("skip_unchanged", True)
        self.retention_days = sc.get("retention_days", 7)

        # 调度器
        self.scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # ============ 任务 ============

    def job_screenshot(self, now: datetime = None):
        """每 N 分钟截图一次"""
        now = now or datetime.now()
        try:
            if self.privacy.should_skip():
                self.log.debug("隐私保护：跳过截图")
                return
            path = self.screenshot.take(now)
            self.log.info("✓ 截图保存: %s", path.name)
            if self.skip_unchanged and self.screenshot.is_unchanged(path):
                path.unlink()
                self.log.debug("屏幕未变化，已删除")
        except Exception as e:
            self.log.error("截图失败: %s\n%s", e, traceback.format_exc())

    def job_analyze_hour(self, now: datetime = None):
        """每小时 HH:50 触发，分析上一个小时的截图"""
        now = now or datetime.now()
        ai = self.config["ai"]
        if not ai.get("enabled", True):
            return
        # 跑在 HH:50，但分析 HH-1 小时
        target_hour = (now.hour - 1) % 24
        target_date = now
        if now.hour == 0:
            target_date = now - timedelta(days=1)

        hour_dir = (self.screenshot.output_dir
                    / target_date.strftime("%Y-%m-%d")
                    / f"{target_hour:02d}")

        if not hour_dir.exists() or not any(hour_dir.glob("*.jpg")):
            self.log.info("跳过分析：%s 没有截图", hour_dir)
            return

        # 幂等：检查状态
        state = load_state("analyzed_hours")
        key = f"{target_date.strftime('%Y-%m-%d')}_{target_hour:02d}"
        if state.get(key):
            self.log.info("已分析过 %s，跳过", key)
            return

        # 读取上一小时总结（如果有）
        prev_summary = ""
        prev_key = f"{(target_date - timedelta(hours=1)).strftime('%Y-%m-%d')}_{(target_hour-1)%24:02d}"
        prev = load_state("hourly_results").get(prev_key)
        if prev and isinstance(prev, dict):
            prev_summary = prev.get("summary", "")

        prompt = ai["prompt_hourly"]
        aggregate_prompt = ai.get("prompt_aggregate_hourly", "")
        # 读上一小时的任务列表（供交叉上下文）
        prev_tasks = ""
        if prev and isinstance(prev, dict):
            prev_tasks = json.dumps(prev.get("tasks", []), ensure_ascii=False, indent=2)[:2000]
        result = self.analyzer.analyze_hour(
            hour_dir, prompt, aggregate_prompt,
            prev_summary=prev_summary, prev_tasks=prev_tasks
        )
        if not result:
            self.log.warning("分析 %s 失败", key)
            return

        # 写时报
        try:
            self.reporter.write_hourly(target_date, target_hour, result)
        except Exception as e:
            self.log.error("写时报失败: %s", e)

        # 保存状态
        state[key] = result
        save_state("analyzed_hours", state)
        results = load_state("hourly_results")
        results[key] = result
        save_state("hourly_results", results)

        # 刷新日报甘特图（不动 AI 总结部分）
        try:
            self.log.info("→ 准备刷新日报甘特图")
            out = self.reporter.update_daily_gantt(target_date, results)
            self.log.info("→ 甘特图已刷新: %s", out)
        except Exception as e:
            import traceback
            self.log.error("刷新日报甘特图失败: %s\n%s", e, traceback.format_exc())

        self.log.info("✓ 完成 %s 分析 + 时报", key)

    def job_daily_report(self, now: datetime = None):
        """每天 23:55 生成日报"""
        now = now or datetime.now()
        ai = self.config["ai"]
        if not ai.get("enabled", True):
            return

        date_str = now.strftime("%Y-%m-%d")
        state = load_state("daily_reports")
        if state.get(date_str):
            self.log.info("日报 %s 已生成，跳过", date_str)
            return

        # 汇总当日所有时报告
        results = load_state("hourly_results")
        today_results = {int(k.split("_")[1]): v
                         for k, v in results.items()
                         if k.startswith(date_str + "_")}

        if not today_results:
            self.log.info("今日无时报告，跳过日报生成")
            return

        # 构造日报 prompt 输入：每个时报告 summary + tasks 列表
        hourly_summaries = []
        for h in sorted(today_results.keys()):
            r = today_results[h]
            if not r:
                continue
            block = [
                f"【{h:02d}:00 - {h:02d}:59】 {r.get('summary', '无')} "
                f"(模式: {r.get('mode', '?')}, 专注: {r.get('focus_score', 0):.2f}, "
                f"产出: {r.get('productivity_score', 0):.2f})"
            ]
            for t in r.get("tasks", []):
                task_line = (
                    f"  - 任务: {t.get('title', '?')}"
                    f" [{t.get('category', '?')}]"
                    f" ({t.get('start', '?')}-{t.get('end', '?')})"
                )
                if t.get("details"):
                    task_line += f" | {t['details']}"
                if t.get("outcomes") and t["outcomes"] != ["none"]:
                    task_line += f" | 产出: {','.join(o for o in t['outcomes'] if o != 'none')}"
                block.append(task_line)
            hourly_summaries.append("\n".join(block))
        hourly_text = "\n\n".join(hourly_summaries) or "（无）"

        # 单独调用一次 AI 汇总
        prompt_daily = ai.get("prompt_daily", "")
        prompt_daily = (prompt_daily
                       .replace("{date}", date_str)
                       .replace("{hourly_summaries}", hourly_text))

        # 收集今日所有截图作为上下文（选有代表性的）
        all_imgs = []
        for h in sorted(today_results.keys()):
            h_dir = (self.screenshot.output_dir / date_str / f"{h:02d}")
            if h_dir.exists():
                imgs = sorted(h_dir.glob("*.jpg"))
                # 每小时取前 1 张 + 末 1 张 + 中间 1 张 = 最多 3 张
                if imgs:
                    if len(imgs) <= 3:
                        all_imgs.extend(imgs)
                    else:
                        all_imgs.append(imgs[0])
                        all_imgs.append(imgs[len(imgs)//2])
                        all_imgs.append(imgs[-1])

        # 用文本模型（minimax/MiniMax-M3）做日报汇总
        self.log.info("开始生成日报 %s，文本模型汇总", date_str)
        daily_result = self.analyzer.call_text(prompt_daily)

        # 兜底：如果 AI 没返回或解析失败，用本地规则汇总
        if not daily_result:
            self.log.warning("AI 汇总日报失败，使用本地规则")
            daily_result = self._fallback_daily_summary(today_results)

        try:
            self.reporter.write_daily(now, daily_result, today_results)
        except Exception as e:
            self.log.error("写日报失败: %s", e)
            return

        state[date_str] = {"generated_at": now.isoformat()}
        save_state("daily_reports", state)

        # 刷新年度日历看板
        try:
            self.reporter.write_calendar_overview(now.year)
        except Exception as e:
            self.log.error("刷新日历看板失败: %s", e)

        self.log.info("✓ 完成日报: %s", date_str)

    def watchdog_check_missing(self, lookback_hours: int = 4) -> list:
        """服务启动时检查最近 N 小时是否有缺失的时报告，自动补跑

        场景：服务被 SIGTERM 杀掉重启后、OpenClaw state-migration 抹掉运行结果等。
        原则：
          - 跳过当前小时（除非已过 50 分）
          - 跳过没有截图的小时
          - 每个补跑间隔 3 秒，避免 OpenClaw rate limit 排队
        """
        from pathlib import Path as _Path
        now = datetime.now()
        state = load_state("analyzed_hours")

        missing = []
        for i in range(lookback_hours):
            check_time = now - timedelta(hours=i)
            # 当前小时且未过 50 分 → 跳过（不补跑进行中的小时）
            if i == 0 and check_time.minute < 50:
                continue
            # 跳到未来小时（不应该）
            if check_time > now:
                continue
            date_str = check_time.strftime("%Y-%m-%d")
            hour_int = check_time.hour
            key = f"{date_str}_{hour_int:02d}"
            if key in state:
                continue  # 已分析过
            # 查截图是否存在
            sc = self.config["screenshot"]
            hour_dir = _Path(sc["output_dir"]).expanduser() / date_str / f"{hour_int:02d}"
            if not hour_dir.exists() or not list(hour_dir.glob("*.jpg")):
                continue
            missing.append((date_str, hour_int, hour_dir))

        if not missing:
            self.log.info("watchdog: 过去 %d 小时无缺失时报告 ✓", lookback_hours)
            return []

        self.log.warning("watchdog: 发现 %d 个缺失时报告: %s", len(missing),
                         [(d, h) for d, h, _ in missing])
        import time as _time

        def _run_one(date_str: str, hour: int, hour_dir):
            try:
                # job_analyze_hour 内部: target_hour = (now.hour - 1) % 24
                # 要分析 hour 小时 → now 应该是 hour+1
                next_hour = (hour + 1) % 24
                next_day = date_str
                if hour == 23:
                    # 跨日：next_hour=0，表示下一天 00:50
                    from datetime import timedelta as _td
                    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
                target_dt = datetime.strptime(f"{next_day} {next_hour:02d}:50", "%Y-%m-%d %H:%M")
                self.log.info("watchdog: 补跑 %s_%02d 开始（触发器 now=%s）",
                              date_str, hour, target_dt.strftime("%Y-%m-%d %H:%M"))
                self.job_analyze_hour(now=target_dt)
                self.log.info("watchdog: 补跑 %s_%02d 完成", date_str, hour)
            except Exception as e:
                import traceback
                self.log.error("watchdog: 补跑 %s_%02d 失败: %s\n%s",
                               date_str, hour, e, traceback.format_exc())

        # 串行补跑（避免并发竞态，state 重复加载导致重复跑）
        for d, h, hd in missing:
            _run_one(d, h, hd)
            _time.sleep(3)  # 间隔，避免 OpenClaw rate limit

        self.log.info("watchdog: 补跑完成")
        return [(d, h) for d, h, _ in missing]

    def _fallback_daily_summary(self, today_results: dict) -> dict:
        """AI 失败时的兜底汇总"""
        all_events = []
        all_insights = []
        for h, r in sorted(today_results.items()):
            if not r:
                continue
            all_events.extend(r.get("events", []))
            all_insights.extend(r.get("insights", []))
        focus_avg = sum(r.get("focus_score", 0.5) for r in today_results.values() if r) / max(len([r for r in today_results.values() if r]), 1)
        prod_avg = sum(r.get("productivity_score", 0.5) for r in today_results.values() if r) / max(len([r for r in today_results.values() if r]), 1)

        # 应用统计
        app_count = {}
        for e in all_events:
            app = e.get("app", "?")
            app_count[app] = app_count.get(app, 0) + 1
        total = sum(app_count.values()) or 1
        top_apps = [[a, round(c * 100 / total)] for a, c in
                    sorted(app_count.items(), key=lambda x: -x[1])[:5]]

        # 类别统计
        cat_count = {}
        for e in all_events:
            c = e.get("category", "其他")
            cat_count[c] = cat_count.get(c, 0) + 1
        cat_total = sum(cat_count.values()) or 1
        time_dist = {k: round(v * 100 / cat_total) for k, v in cat_count.items()}

        return {
            "headline": f"今日 {len([r for r in today_results.values() if r])} 个有效时段，平均专注度 {focus_avg:.2f}",
            "core_work": [r.get("summary", "") for h, r in sorted(today_results.items()) if r][:5],
            "time_distribution": time_dist,
            "top_apps": top_apps,
            "key_outputs": [],
            "focus_score": focus_avg,
            "productivity_score": prod_avg,
            "highlights": [],
            "lowlights": [],
            "tomorrow_suggestions": all_insights[:3] if all_insights else ["保持当前节奏"],
        }

    def job_cleanup(self):
        """每天清理过期截图 + 联动清理对应时报告 state（避免鬼影数据）"""
        cutoff_date = (datetime.now() - timedelta(days=self.retention_days)).strftime("%Y-%m-%d")
        # 1. 删过期截图
        self.screenshot.cleanup_old(self.retention_days)
        # 2. 联动清理 state 里 < cutoff_date 的条目
        for state_name in ("hourly_results", "analyzed_hours", "daily_reports"):
            data = load_state(state_name)
            before = len(data)
            data = {k: v for k, v in data.items() if k.split("_")[0] >= cutoff_date}
            removed = before - len(data)
            if removed:
                save_state(state_name, data)
                self.log.info("清理 state[%s]: 删除 %d 条 < %s 的鬼影数据",
                              state_name, removed, cutoff_date)

    # ============ 调度注册 ============

    def start(self):
        sc = self.config["screenshot"]
        ai = self.config["ai"]

        # 截图 job
        self.scheduler.add_job(
            self.job_screenshot,
            IntervalTrigger(minutes=sc["interval_minutes"]),
            id="screenshot",
            name="截图",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now() + timedelta(seconds=5),
        )

        # 小时分析 job
        if ai.get("enabled", True):
            minute = ai.get("hourly_run_at_minute", 50)
            self.scheduler.add_job(
                self.job_analyze_hour,
                CronTrigger(minute=minute),
                id="analyze_hour",
                name=f"每小时第 {minute} 分 AI 分析",
                max_instances=1,
                coalesce=True,
            )

        # 补漏 job：每 15 分钟扫一次过去 3 小时，补上任何 missing 小时
        # 原因：HH:50 cron 只检查 HH-1，watchdog 补了 HH-1 后 cron 会跳过，
        # 导致下一小时的 HH 在等到下下小时 HH:50 才被分析（如 20 点要等 21:50）
        if ai.get("enabled", True):
            self.scheduler.add_job(
                self.job_check_missing_hours,
                IntervalTrigger(minutes=15),
                id="check_missing_hours",
                name="每 15 分钟补漏缺失时报告",
                max_instances=1,
                coalesce=True,
            )

        # 日报 job
        if ai.get("enabled", True):
            hh, mm = ai.get("daily_run_at", "23:55").split(":")
            self.scheduler.add_job(
                self.job_daily_report,
                CronTrigger(hour=int(hh), minute=int(mm)),
                id="daily_report",
                name=f"每日 {hh}:{mm} 日报",
                max_instances=1,
                coalesce=True,
            )

        # 清理 job（每天凌晨 3 点）
        self.scheduler.add_job(
            self.job_cleanup,
            CronTrigger(hour=3, minute=0),
            id="cleanup",
            name="清理过期截图",
        )

        # 信号处理
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self.log.info("调度已启动：")
        for job in self.scheduler.get_jobs():
            # APScheduler 3.11+：未传 next_run_time 的 job 没有该属性
            next_run = getattr(job, "next_run_time", None) or "未调度（首次按 trigger 计算）"
            self.log.info("  - %s (id=%s) -> next: %s",
                         job.name, job.id, next_run)
        self.log.info("PID=%d", os.getpid())
        # Watchdog：服务启动时检查过去 4 小时的缺失时报告，自动补跑
        try:
            self.watchdog_check_missing(lookback_hours=4)
        except Exception as e:
            self.log.error("watchdog 异常: %s", e)
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.log.info("收到退出信号，正在停止...")

    def _handle_signal(self, signum, frame):
        self.log.info("收到信号 %d，优雅退出", signum)
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        sys.exit(0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="DayScope")
    parser.add_argument("--once-screenshot", action="store_true",
                        help="只截一次图就退出（调试用）")
    parser.add_argument("--write-calendar", metavar="YYYY", type=int, nargs="?",
                        help="生成年度日历看板（默认当前年）")
    parser.add_argument("--watchdog", action="store_true",
                        help="手动触发 watchdog 检查并补跑缺失时报告")
    parser.add_argument("--once-analyze", metavar="YYYY-MM-DD/HH",
                        help="分析指定小时然后退出（调试用）")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args()

    tracker = Tracker(Path(args.config))

    if args.write_calendar is not None:
        year = args.write_calendar or datetime.now().year
        out = tracker.reporter.write_calendar_overview(year)
        print(f"已生成日历看板: {out}")
        return

    if args.watchdog:
        missing = tracker.watchdog_check_missing(lookback_hours=4)
        if missing:
            print(f"已补跑: {missing}")
        else:
            print("过去 4 小时无缺失时报告")
        return

    if args.once_screenshot:
        tracker.job_screenshot()
        return

    if args.once_analyze:
        date_str, hour_str = args.once_analyze.split("/")
        date = datetime.strptime(date_str, "%Y-%m-%d")
        hour = int(hour_str)
        hour_dir = (Path(tracker.config["screenshot"]["output_dir"]).expanduser()
                    / date_str / hour_str)
        prompt = tracker.config["ai"]["prompt_hourly"]
        result = tracker.analyzer.analyze_hour(
            hour_dir, prompt,
            tracker.config["ai"].get("prompt_aggregate_hourly", "")
        )
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            tracker.reporter.write_hourly(date, hour, result)
            # 保存状态 + 刷新甘特图
            key = f"{date_str}_{hour:02d}"
            results = load_state("hourly_results")
            results[key] = result
            save_state("hourly_results", results)
            try:
                tracker.reporter.update_daily_gantt(date, results)
            except Exception as e:
                print(f"刷新甘特图失败: {e}")
        return

    tracker.start()


if __name__ == "__main__":
    main()