"""获取当前活动窗口标题（用于隐私过滤）"""
import subprocess
import logging

log = logging.getLogger(__name__)


def get_active_window_title() -> str:
    """获取当前活动窗口标题。多 Wayland / X11 兼容方案。"""
    # GNOME Wayland 下用 gdbus 调 Mutter 的 Window
    try:
        out = subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", "org.gnome.Shell",
             "--object-path", "/org/gnome/Shell/Extensions/Windows",
             "--method", "org.gnome.Shell.Extensions.Windows.List"],
            capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0:
            # 解析返回的 ( [...], ) 格式
            return out.stdout[:500]
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # 退化方案：用 xdotool（X11）
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # 再退化：xprop
    try:
        out = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    return ""