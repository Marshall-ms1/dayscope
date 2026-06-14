"""AI 分析模块：两步分析
第一步（视觉）：每张截图用 M3 视觉模型识别成 event
第二步（归纳）：用 M3 文本模型把 60 个 event 归纳成 3-7 个"任务"
"""
import json
import re
import subprocess
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)


class AIAnalyzer:
    def __init__(self, model: str = "minimax-cn/MiniMax-M3",
                 max_images_per_call: int = 18,
                 timeout_seconds: int = 300):
        self.model = model
        self.max_images_per_call = max_images_per_call
        self.timeout = timeout_seconds

    def analyze_hour(self, hour_dir: Path,
                     vision_prompt: str,
                     aggregate_prompt: str,
                     prev_summary: str = "",
                     prev_tasks: str = "") -> dict:
        """分析一小时的所有截图，两步：视觉识别 → 任务归纳

        返回结构：
        {
          "summary": "本小时一句话",
          "mode": "深度工作",
          "focus_score": 0.7,
          "productivity_score": 0.8,
          "events": [{time, app, category, activity, details, outcome}, ...],
          "tasks": [{title, category, start, end, details, outcomes, apps}, ...],
          "insights": ["洞察 1", ...]
        }
        """
        images = sorted(hour_dir.glob("*.jpg"))
        if not images:
            log.warning("目录 %s 没有截图", hour_dir)
            return None

        date_str = hour_dir.parent.name  # "YYYY-MM-DD"
        hour_str = hour_dir.name         # "HH"

        log.info("开始分析 %s %s:00 - %s:59，共 %d 张截图",
                 date_str, hour_str, hour_str, len(images))

        # ============ 第一步：视觉识别，每张图一个 event ============
        rendered_vision = (vision_prompt
            .replace("{date}", date_str)
            .replace("{hour}", hour_str)
            .replace("{count}", str(len(images)))
            .replace("{prev_summary}", prev_summary or "（无）"))

        # 1.1 先用 PIL 算相邻图视觉差，识别"未变化"图，标挂机跳过 AI 调用
        visual_diff_map = self._compute_visual_diff(images)
        unchanged_indices = [i for i, d in visual_diff_map.items() if d < 5.0]
        log.info("视觉去重：%d / %d 张与上张几乎相同（不需要 AI 识别）",
                 len(unchanged_indices), len(images))

        events = []
        # 先把“未变化”图标为挂机 event
        for i in unchanged_indices:
            fname = images[i].stem
            time_str = ""
            if len(fname) == 15 and fname[8] == "-":
                time_str = fname
            events.append({
                "app": "?",
                "category": "挂机",
                "activity": "电脑前休息",
                "details": "未产生交互，屏幕与上分钟几乎一致",
                "outcome": "none",
                "_raw_time": time_str,
                "_raw_filename": fname,
                "time": f"{time_str[9:11]}:{time_str[11:13]}" if time_str else "",
            })
        # 剩下的"可能有变化"的图，调用 AI 识别
        images_to_recognize = [img for i, img in enumerate(images) if i not in unchanged_indices]
        if images_to_recognize:
            for batch in self._chunks(images_to_recognize, self.max_images_per_call):
                log.info("视觉 batch %d 张（图 %s - %s）", len(batch),
                         batch[0].name, batch[-1].name)
                batch_events = self._call_vision_batch(batch, rendered_vision)
                if batch_events:
                    events.extend(batch_events)

        if not events:
            log.warning("视觉识别全部失败，无法做任务归纳")
            return None

        # 按时间排序（filename = YYYYMMDD-HHMMSS.jpg）
        events.sort(key=lambda e: e.get("_raw_time", ""))
        log.info("视觉识别完成，得到 %d 个 event", len(events))

        # ============ 第二步：任务归纳 ============
        log.info("开始任务归纳（%d 个 event → 3-7 个 task）", len(events))
        aggregate = self._call_text_aggregate(
            events=events,
            prompt_template=aggregate_prompt,
            prev_tasks=prev_tasks,
            hour_str=hour_str,
        )

        if not aggregate:
            log.warning("任务归纳失败，fallback 到原始 event 列表")
            return {
                "summary": "（任务归纳失败）",
                "mode": "混合",
                "focus_score": 0.5,
                "productivity_score": 0.5,
                "events": events,
                "tasks": [],
                "insights": [],
            }

        # 兜底：补全 task 缺漏的 start/end/outcomes
        tasks = self._fill_task_gaps(aggregate.get("tasks", []), events)

        # 程序计算 focus/productivity（不受 AI 幻觉影响）
        # focus = 1 - 挂机事件占比
        idle_count = sum(1 for e in events if e.get("category") in ("挂机", "休息"))
        total = len(events) if events else 1
        idle_ratio = idle_count / total
        computed_focus = max(0.0, 1.0 - idle_ratio)
        # productivity = 有 outcome 不为 none 的事件占比
        productive_count = sum(1 for e in events
                               if e.get("outcome") not in ("none", "", None))
        computed_productivity = productive_count / total

        # 覆盖 AI 的 幻觉分数（如果 AI 算的 < 0.1 但我们算 0.0，取我们为准）
        ai_focus = aggregate.get("focus_score", 0.5)
        ai_productivity = aggregate.get("productivity_score", 0.5)
        # 以我们算的为准，AI 分数仅作参考
        final_focus = round(computed_focus, 2)
        final_productivity = round(computed_productivity, 2)

        return {
            "summary": aggregate.get("summary", ""),
            "mode": aggregate.get("mode", "混合"),
            "focus_score": final_focus,
            "productivity_score": final_productivity,
            "events": events,
            "tasks": tasks,
            "insights": aggregate.get("insights", []),
        }

    # =================== 视觉识别 ===================
    def _call_vision_batch(self, images: list, prompt: str) -> list:
        """调 M3 视觉模型识别一批截图，返回 [{time, app, category, activity, details, outcome}, ...]"""
        cmd = ["openclaw", "infer", "image", "describe-many", "--json"]
        for img in images:
            cmd.extend(["--file", str(img)])
        cmd.extend(["--prompt", prompt])
        cmd.extend(["--model", self.model])
        cmd.extend(["--timeout-ms", str(self.timeout * 1000)])

        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout + 30
            )
        except subprocess.TimeoutExpired:
            log.error("视觉调用超时（%ds）", self.timeout)
            return []
        except FileNotFoundError:
            log.error("找不到 openclaw 命令，请确认 PATH")
            return []

        if out.returncode != 0:
            log.error("openclaw vision 退出码 %d: %s", out.returncode, out.stderr[:500])
            return []

        text = out.stdout.strip()
        if not text:
            return []

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.error("vision 输出不是 JSON: %s", text[:200])
            return []

        outputs = data.get("outputs", [])
        events = []
        for o in outputs:
            path = o.get("path", "")
            text_out = o.get("text", "")
            # 从文件名提取时间戳
            # /path/to/20260614-130218.jpg → 20260614-130218
            fname = Path(path).stem
            time_str = ""
            if len(fname) == 15 and fname[8] == "-":  # YYYYMMDD-HHMMSS
                time_str = fname  # 完整时间戳

            # 解析 text 为 JSON
            event = self._parse_event_json(text_out)
            if event:
                event["_raw_time"] = time_str
                event["_raw_filename"] = fname
                # 加可读时间 HH:MM
                if time_str:
                    event["time"] = f"{time_str[9:11]}:{time_str[11:13]}"
                events.append(event)
        return events

    @staticmethod
    def _parse_event_json(text: str) -> dict:
        """从 AI 输出的文本里提取 JSON（处理 AI 有时加引号/markdown 标记的情况）"""
        text = text.strip()
        # 去 ```json ... ``` 包裹
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # 找第一个 { 到最后一个 }
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    # =================== 任务归纳 ===================
    def _call_text_aggregate(self, events: list, prompt_template: str,
                             prev_tasks: str, hour_str: str = "00") -> dict:
        """用 M3 文本模型把 events 归纳成 tasks"""
        # 简化 events 用于 prompt（去掉 _raw_ 等内部字段）
        simple_events = []
        for e in events:
            simple_events.append({
                "time": e.get("time", "?"),
                "app": e.get("app", "?"),
                "category": e.get("category", "?"),
                "activity": e.get("activity", "?"),
                "details": e.get("details", ""),
                "outcome": e.get("outcome", "none"),
            })

        events_json = json.dumps(simple_events, ensure_ascii=False, indent=2)
        prompt = (prompt_template
            .replace("{events_json}", events_json)
            .replace("{prev_tasks}", prev_tasks or "（无）")
            .replace("{hour}", hour_str))

        result = self.call_text(prompt)
        return result

    # =================== 文本模型调用 ===================
    def call_text(self, prompt: str, model: str = None) -> dict:
        """调用 M3 文本模型"""
        model = model or self.model
        cmd = ["openclaw", "infer", "model", "run",
               "--model", model,
               "--prompt", prompt,
               "--json"]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout + 30
            )
        except subprocess.TimeoutExpired:
            log.error("文本模型调用超时")
            return None
        except FileNotFoundError:
            log.error("找不到 openclaw 命令")
            return None

        if out.returncode != 0:
            log.error("openclaw model run 退出码 %d: %s", out.returncode, out.stderr[:500])
            return None

        text = out.stdout.strip()
        if not text:
            return None

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                if "outputs" in data and isinstance(data["outputs"], list):
                    if data["outputs"] and "text" in data["outputs"][0]:
                        return self._parse_event_json(data["outputs"][0]["text"])
                if "text" in data:
                    return self._parse_event_json(data["text"])
            return data
        except json.JSONDecodeError:
            return self._parse_event_json(text)

    # =================== 工具 ===================
    def _chunks(self, lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def _compute_visual_diff(self, images: list) -> dict:
        """计算相邻图片的像素差（0=完全相同，越大越不同）

        返回 {idx: diff_score}。第一张默认为 999（需要 AI 识别）
        """
        from PIL import Image
        diffs = {0: 999.0}  # 第一张总需要 AI 看
        prev_small = None
        for i, img_path in enumerate(images):
            try:
                img = Image.open(img_path).convert("L").resize((64, 64), Image.LANCZOS)
                if prev_small is not None:
                    p1 = list(prev_small.getdata())
                    p2 = list(img.getdata())
                    diff = sum(abs(a - b) for a, b in zip(p1, p2)) / len(p1)
                    diffs[i] = diff
                prev_small = img
            except Exception as e:
                log.warning("算视觉差失败 %s: %s", img_path, e)
                diffs[i] = 999.0
        return diffs

    def _fill_task_gaps(self, tasks: list, events: list) -> list:
        """兜底逻辑：补全 AI 可能漏填的 start/end/outcomes/details
        启发式：按 category 切分 events 到对应 task
        """
        if not tasks:
            return tasks

        # 整理 events：按 category+activity 关键词分
        ev_by_time = {e.get("time", ""): e for e in events}
        ev_times = sorted([t for t in ev_by_time if t])

        for t in tasks:
            # 1. 补 start/end：从 events 推断
            start = t.get("start", "").strip()
            end = t.get("end", "").strip()
            if not start or not end or start == "?" or end == "?":
                # 取第一个和最后一个 event 的时间
                if ev_times:
                    t["start"] = t.get("start") or ev_times[0]
                    t["end"] = t.get("end") or ev_times[-1]
                else:
                    t["start"] = t.get("start") or "--:--"
                    t["end"] = t.get("end") or "--:--"

            # 2. 补 outcomes：至少要有一个元素
            if not t.get("outcomes"):
                t["outcomes"] = ["none"]

            # 3. 补 apps：至少要有一个（从 title 猜不到，填空列表）

            # 4. 标题截断：超过 12 个字告警（不强制截，会让 AI 下次做好）
            title = t.get("title", "")
            if len(title) > 20:
                log.warning("任务标题过长 (%d 字): %s", len(title), title)

        return tasks
