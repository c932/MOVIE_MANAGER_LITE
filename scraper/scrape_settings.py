"""本机刮削配置；与旧 scrape_config.json 合并并原子保存。"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from urllib.parse import urlsplit

from parsers.nfo_writer import _atomic_write
from utils.app_paths import resolve_data_file


@dataclass
class ScrapeSettings:
    tmdb_api_key: str = ""
    tmdb_token: str = ""
    omdb_api_key: str = ""
    language: str = "zh-CN"
    proxy: str = ""
    timeout: int = 20
    douban_delay: float = 1.5

    def validate(self) -> None:
        if not isinstance(self.timeout, int) or not 1 <= self.timeout <= 120:
            raise ValueError("请求超时应为 1–120 秒")
        if not isinstance(self.douban_delay, (int, float)) or not math.isfinite(self.douban_delay) or not 0 <= self.douban_delay <= 60:
            raise ValueError("豆瓣请求间隔应为 0–60 秒")
        if self.proxy:
            try:
                parsed = urlsplit(self.proxy)
                valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("代理地址应为 http://主机:端口 或 https://主机:端口，暂不支持认证代理")

    @classmethod
    def load(cls) -> ScrapeSettings:
        try:
            value = json.loads(resolve_data_file("scrape_config.json").read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return cls()
            config = cls(**{f.name: value[f.name] for f in fields(cls) if f.name in value})
            config.validate()
            return config
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        self.validate()
        path = resolve_data_file("scrape_config.json")
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing.update(asdict(self))
        _atomic_write(path, json.dumps(existing, ensure_ascii=False, indent=2).encode("utf-8"))
