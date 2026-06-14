"""隐私过滤：基于窗口标题判断是否跳过截图"""
import logging
from .window import get_active_window_title

log = logging.getLogger(__name__)


class PrivacyGuard:
    def __init__(self, enabled: bool, blacklist: list):
        self.enabled = enabled
        self.blacklist = [kw.lower() for kw in (blacklist or [])]

    def should_skip(self) -> bool:
        """检测当前窗口是否在黑名单中"""
        if not self.enabled or not self.blacklist:
            return False
        title = get_active_window_title().lower()
        if not title:
            return False
        for kw in self.blacklist:
            if kw in title:
                log.info("隐私保护：跳过截图（窗口标题匹配黑名单 '%s'）", kw)
                return True
        return False