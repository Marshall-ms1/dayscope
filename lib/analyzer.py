"""AI 分析模块：调用 openclaw CLI 调用 MiniMax-VL-01 分析截图"""
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

    def analyze_hour(self, hour_dir: Path, prompt: str,
                     prev_summary: str = "") -> dict:
        """分析一小时的所有截图，返回结构化 JSON"""
        images = sorted(hour_dir.glob("*.jpg"))
        if not images:
            log.warning("目录 %s 没有截图", hour_dir)
            return None

        # 文件名形如 HH/MM-SS.jpg，取 MM-SS 作为时间
        first = images[0].stem  # "MM-SS"
        date_str = hour_dir.parent.name  # "YYYY-MM-DD"
        hour_str = hour_dir.name         # "HH"
        start_ts = f"{hour_str}:{first.split('-')[0]}"
        end_ts = f"{hour_str}:{images[-1].stem.split('-')[0]}"

        # 渲染 prompt
        rendered = (prompt
                   .replace("{date}", date_str)
                   .replace("{hour}", hour_str)
                   .replace("{count}", str(len(images)))
                   .replace("{prev_summary}", prev_summary or "（无）"))

        log.info("开始分析 %s %s:00 - %s:59，共 %d 张截图",
                 date_str, hour_str, hour_str, len(images))

        # 分批调用（避免单次太大）
        all_results = []
        for batch in self._chunks(images, self.max_images_per_call):
            log.info("本批 %d 张（图 %s - %s）", len(batch),
                     batch[0].name, batch[-1].name)
            result = self._call_describe_many(batch, rendered)
            if result:
                all_results.append(result)

        # 合并多批结果（如果有）
        if not all_results:
            return None
        if len(all_results) == 1:
            return all_results[0]
        return self._merge_results(all_results)

    def _call_describe_many(self, images: list, prompt: str) -> dict:
        """调用 openclaw infer image describe-many。
        返回 {outputs: [{path, text}, ...]} 结构，需要按单图独立解析后再合并。"""
        cmd = ["openclaw", "infer", "image", "describe-many", "--json"]
        for img in images:
            cmd.extend(["--file", str(img)])
        cmd.extend(["--prompt", prompt])
        # model 参数已含 provider 前缀（如 minimax-cn/MiniMax-M3），不再拼
        cmd.extend(["--model", self.model])
        cmd.extend(["--timeout-ms", str(self.timeout * 1000)])

        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout + 30
            )
        except subprocess.TimeoutExpired:
            log.error("AI 调用超时（%ds）", self.timeout)
            return None
        except FileNotFoundError:
            log.error("找不到 openclaw 命令，请确认 PATH")
            return None

        if out.returncode != 0:
            log.error("openclaw 退出码 %d: %s", out.returncode,
                      out.stderr[:500])
            return None

        text = out.stdout.strip()
        if not text:
            return None

        # openclaw describe-many 返回 {"outputs":[{"path","text"}, ...]}
        # 每张图独立分析，text 是 AI 的原始文本（按 prompt 要求是 JSON）
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.error("openclaw 输出不是 JSON: %s", text[:300])
            return None

        if not isinstance(data, dict) or "outputs" not in data:
            log.error("openclaw 输出缺少 outputs 字段")
            return None

        per_image = []  # [(timestamp_from_path, parsed_dict), ...]
        for item in data["outputs"]:
            path_str = item.get("path", "")
            text_str = item.get("text", "")
            # 从路径提取时间戳 "HH/MM-SS.jpg"
            ts = self._extract_ts(path_str)
            parsed = self._extract_json_from_text(text_str)
            if parsed is not None:
                per_image.append((ts, parsed))
            else:
                log.warning("无法解析单图输出: %s", text_str[:200])

        if not per_image:
            return None

        return self._combine_per_image(per_image)

    @staticmethod
    def _extract_ts(path_str: str) -> str:
        """从 'screenshots/2026-06-13/14/14-25.jpg' 提取 '14:25'"""
        import re as _re
        name = Path(path_str).stem  # "14-25"
        parts = name.split("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        return name

    @staticmethod
    def _extract_json_from_text(text: str):
        """从 AI 返回的文本中提取 JSON 对象"""
        if not text:
            return None
        # 尝试 1: 整体是 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试 2: ```json ... ``` 块
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 尝试 3: 第一个 { ... } 块
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None

    def _combine_per_image(self, per_image: list) -> dict:
        """把单图结果合并成小时级别。
        per_image: [(timestamp_str, parsed_dict), ...]"""
        per_image.sort(key=lambda x: x[0])

        events = []
        app_durations = {}  # app -> 分钟数（估算）
        category_minutes = {}
        prev_ts = None
        prev_app = None
        prev_activity = None

        for i, (ts, d) in enumerate(per_image):
            app = d.get("app", "?")
            activity = d.get("activity", "")
            details = d.get("details", "")
            category = d.get("category", "未知")

            # 估算持续时间（基于相邻截图间隔）
            if prev_ts:
                prev_h, prev_m = map(int, prev_ts.split(":"))
                cur_h, cur_m = map(int, ts.split(":"))
                duration = (cur_h * 60 + cur_m) - (prev_h * 60 + prev_m)
                if duration < 1:
                    duration = 2  # 默认 2 分钟
                # 把上一个 event 的 duration 算出来
                if events and duration > 0:
                    events[-1]["end"] = ts
                app_durations[prev_app] = app_durations.get(prev_app, 0) + duration
                category_minutes[prev_category] = category_minutes.get(prev_category, 0) + duration
            else:
                duration = 0  # 第一个没有 end

            events.append({
                "start": ts,
                "end": ts,  # 后续会被下一轮的 prev_ts 更新
                "app": app,
                "category": category,
                "activity": activity,
                "details": details,
            })
            prev_ts = ts
            prev_app = app
            prev_activity = activity
            prev_category = category

        # 最后一段：延伸到小时末
        if events:
            hour_str = events[0]["start"].split(":")[0]
            events[-1]["end"] = f"{hour_str}:59"
            app_durations[prev_app] = app_durations.get(prev_app, 0) + 2
            category_minutes[prev_category] = category_minutes.get(prev_category, 0) + 2

        # 合并相邻的同 app events
        events = self._merge_adjacent_events(events)

        # 评分
        total_minutes = sum(app_durations.values()) or 1
        max_app_pct = max(app_durations.values()) / total_minutes if app_durations else 0
        focus_score = round(max_app_pct, 2)  # 单应用占比 = 专注度粗估
        cat_deep = category_minutes.get("深度工作", 0) + category_minutes.get("调试", 0)
        productivity_score = round(cat_deep / total_minutes, 2)

        # 主模式
        main_mode = "混合"
        if category_minutes:
            main_cat = max(category_minutes.items(), key=lambda x: x[1])[0]
            mode_map = {
                "深度工作": "深度工作",
                "调试": "深度工作",
                "文档": "文档编写",
                "沟通": "沟通协作",
                "会议": "会议",
                "学习": "学习",
                "碎片": "碎片浏览",
            }
            main_mode = mode_map.get(main_cat, main_cat)

        # 应用 Top
        top_apps = [[a, round(m * 100 / total_minutes)] for a, m in
                    sorted(app_durations.items(), key=lambda x: -x[1])[:5]]

        # 总结
        summary = self._make_summary(events, main_mode, focus_score, top_apps)

        # 洞察（基于规则）
        insights = self._make_insights(events, app_durations, category_minutes)

        return {
            "events": events,
            "summary": summary,
            "mode": main_mode,
            "focus_score": focus_score,
            "productivity_score": productivity_score,
            "top_apps": top_apps,
            "key_outputs": self._extract_outputs(events),
            "insights": insights,
        }

    @staticmethod
    def _merge_adjacent_events(events: list) -> list:
        """合并相邻的同 app events"""
        if not events:
            return events
        merged = [events[0].copy()]
        for ev in events[1:]:
            last = merged[-1]
            if (ev["app"] == last["app"] and
                ev["category"] == last["category"] and
                ev["activity"] == last["activity"]):
                last["end"] = ev["end"]
                if ev["details"] and ev["details"] != last["details"]:
                    last["details"] = (last["details"] + " | " + ev["details"])[:200]
            else:
                merged.append(ev.copy())
        return merged

    @staticmethod
    def _make_summary(events, mode, focus_score, top_apps=None):
        if not events:
            return "（无活动）"
        if top_apps and len(top_apps) >= 1:
            top = top_apps[0]
            app_name = top[0] if isinstance(top, (list, tuple)) else top
            return f"{mode}·{app_name} 占 {top[1]}%"
        apps = list({e["app"] for e in events})
        if len(apps) == 1:
            return f"{mode}·专注使用 {apps[0]}"
        return f"{mode}·切换 {len(apps)} 个应用"

    @staticmethod
    def _make_insights(events, app_durations, category_minutes):
        ins = []
        if not events:
            return ins
        total = sum(app_durations.values()) or 1
        top_app, top_min = max(app_durations.items(), key=lambda x: x[1])
        top_pct = round(top_min * 100 / total)
        # 切屏频率（合并后 events 之间的 app 切换）
        switches = sum(1 for i in range(1, len(events)) if events[i]["app"] != events[i-1]["app"])
        if switches >= 3:
            ins.append(f"本小时切屏 {switches} 次，碎片化较严重，建议关闭非必要通知")
        elif switches >= 2:
            ins.append(f"本小时切换 {switches} 次应用，节奏略散，可考虑一次性处理同类任务")
        elif switches == 0 and len(events) >= 2:
            ins.append(f"零切屏深度心流，全程专注 {top_app}")
        # 深度工作比例
        deep = category_minutes.get("深度工作", 0) + category_minutes.get("调试", 0)
        if deep / total >= 0.7:
            ins.append(f"深度工作占比 {round(deep*100/total)}%，本小时产出质量预期高")
        elif deep / total <= 0.3 and total > 10:
            ins.append(f"深度工作仅 {round(deep*100/total)}%，多数时间在浅层任务")
        # 单一应用霸屏
        if top_pct >= 80:
            ins.append(f"{top_app} 占 {top_pct}% 时间，单点聚焦")
        elif top_pct < 40 and len(app_durations) >= 3:
            ins.append(f"应用分布较散（{len(app_durations)} 个），最常用 {top_app} 也仅 {top_pct}%")
        return ins[:3]

    @staticmethod
    def _extract_outputs(events):
        outputs = []
        for e in events:
            if e.get("details") and len(outputs) < 3:
                outputs.append(f"{e['activity']} - {e['details']}")
        return outputs

    def _merge_results(self, results: list) -> dict:
        """合并多批的结构化结果"""
        all_events = []
        insights = []
        for r in results:
            if not r:
                continue
            all_events.extend(r.get("events", []))
            insights.extend(r.get("insights", []))
        if not all_events:
            return None
        return {
            "events": all_events,
            "summary": results[0].get("summary", ""),
            "mode": results[0].get("mode", "混合"),
            "focus_score": sum(r.get("focus_score", 0.5) for r in results) / len(results),
            "productivity_score": sum(r.get("productivity_score", 0.5) for r in results) / len(results),
            "insights": insights[:5],
        }

    def _chunks(self, lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def call_text(self, prompt: str, model: str = "minimax-cn/MiniMax-M3") -> dict:
        """调用文本模型（用于日报等不需要视觉的任务）"""
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
            log.error("openclaw model run 失败: %s", out.stderr[:300])
            return None

        text = out.stdout.strip()
        if not text:
            return None

        try:
            data = json.loads(text)
            # openclaw model run 输出 {"outputs":[{"text":"..."}]}
            if isinstance(data, dict):
                if "outputs" in data and isinstance(data["outputs"], list):
                    if data["outputs"] and "text" in data["outputs"][0]:
                        return self._extract_json_from_text(data["outputs"][0]["text"])
                if "text" in data:
                    return self._extract_json_from_text(data["text"])
            return data
        except json.JSONDecodeError:
            return self._extract_json_from_text(text)