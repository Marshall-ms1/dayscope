"""截图模块：全屏截图 + 缩放压缩 + 变化检测

走 GNOME 扩展（screenshot-helper@local）导出 dbus 接口
cn.local.ScreenshotHelper.Screenshot
—— 这个接口跑在 mutter 进程里，享有同源信任，可以调 Meta.Screenshot。

为什么不用 mss / gnome-screenshot / portal:
- mutter 49 把 org.gnome.Shell.Screenshot 列为"private API"，所有外部调用都拒。
- 扩展进程是 mutter 信任的唯一路径。
"""
import os
import json
import subprocess
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from PIL import Image

log = logging.getLogger(__name__)

DBUS_NAME = "cn.local.ScreenshotHelper"
DBUS_PATH = "/cn/local/ScreenshotHelper"
DBUS_IFACE = DBUS_NAME  # interface name == bus name
DBUS_TIMEOUT = 15  # 秒


class ScreenshotError(RuntimeError):
    pass


class ScreenshotTaker:
    def __init__(self, output_dir: Path, jpeg_quality: int = 70,
                 max_dimension: int = 1920,
                 include_cursor: bool = False,
                 flash: bool = False):
        self.output_dir = Path(output_dir).expanduser()
        self.jpeg_quality = jpeg_quality
        self.max_dimension = max_dimension
        self.include_cursor = include_cursor
        self.flash = flash
        self._last_hash = None

    def _call_helper(self, method: str, args: list, timeout: int = DBUS_TIMEOUT):
        """调 dbus 方法，参数必须是 gdbus 接受的文本形式。"""
        arg_str = " ".join(str(a) for a in args)
        cmd = [
            "gdbus", "call", "--session",
            "--dest", DBUS_NAME,
            "--object-path", DBUS_PATH,
            "--method", f"{DBUS_IFACE}.{method}",
            "--timeout", str(timeout),
        ] + args
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 5
            )
        except subprocess.TimeoutExpired:
            raise ScreenshotError(f"dbus call timeout: {method}")
        if result.returncode != 0:
            raise ScreenshotError(
                f"dbus call failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout.strip()

    def take(self, now: datetime = None) -> Path:
        """截全屏，返回保存的文件路径。"""
        now = now or datetime.now()
        hour_dir = self.output_dir / now.strftime("%Y-%m-%d") / now.strftime("%H")
        hour_dir.mkdir(parents=True, exist_ok=True)
        filename = hour_dir / now.strftime("%Y%m%d-%H%M%S.jpg")

        # dbus 参数：b include_cursor, b flash, s filename
        # 调成功后 mutter 会写一个 PNG 到 filename（文件名不能变 .jpg）
        png_filename = filename.with_suffix(".png")
        try:
            out = self._call_helper("Screenshot", [
                str(bool(self.include_cursor)).lower(),
                str(bool(self.flash)).lower(),
                str(png_filename),
            ])
            # 返回 '(true, '/path/to/file.png')'
            # 解析出 (success, path)
            if "(true," not in out and "(false," not in out:
                raise ScreenshotError(f"unexpected dbus response: {out!r}")
            if "(true," not in out:
                raise ScreenshotError(f"screenshot failed: {out}")

            if not png_filename.exists():
                raise ScreenshotError(
                    f"dbus said success but file not created: {png_filename}"
                )

            # PNG → JPEG，缩放
            img = Image.open(png_filename).convert("RGB")
            if self.max_dimension > 0 and max(img.size) > self.max_dimension:
                img.thumbnail((self.max_dimension, self.max_dimension), Image.LANCZOS)
            img.save(filename, "JPEG", quality=self.jpeg_quality, optimize=True)

            # 清掉临时 PNG
            try:
                png_filename.unlink()
            except OSError:
                pass

            return filename
        except ScreenshotError as e:
            log.error("Screenshot failed: %s", e)
            raise

    def is_unchanged(self, file_path: Path) -> bool:
        """通过像素采样判断是否变化（避免鼠标光标位置不同被误判）

        为何不用 md5：鼠标光标在一个像素位变动会改变 hash，但屏幕内容几乎不变
        为何不用 perceptual hash：额外装包（imagehash），降速度
        抽样：缩到 64x64 灰度 + 采样上中下左中右 9 点 + 跟上次 hash 比对
        """
        try:
            from PIL import Image
        except ImportError:
            # 退化为 md5
            h = hashlib.md5(file_path.read_bytes()).hexdigest()
            unchanged = (h == self._last_hash)
            self._last_hash = h
            return unchanged

        try:
            img = Image.open(file_path).convert("L").resize((64, 64), Image.LANCZOS)
        except Exception:
            return False

        # 采样 9 个区域：四角 + 边中 + 中心
        samples = []
        w, h = img.size
        for y in [0, h//4, h//2, 3*h//4, h-1]:
            for x in [0, w//4, w//2, 3*w//4, w-1]:
                samples.append(img.getpixel((x, y)))
        h_visual = hashlib.md5(bytes(samples)).hexdigest()
        unchanged = (h_visual == self._last_hash)
        self._last_hash = h_visual
        return unchanged

    def cleanup_old(self, days: int):
        """清理 N 天前的截图"""
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        count = 0
        for f in self.output_dir.rglob("*.jpg"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                count += 1
        if count:
            log.info("已清理 %d 张过期截图（>%d 天）", count, days)