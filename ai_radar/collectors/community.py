"""Adapters for large developer communities with stable feed bridges."""
from __future__ import annotations

from urllib.parse import urlparse

from ai_radar.collectors.juejin import JuejinCollector
from ai_radar.collectors.rss import RSSCollector


COMMUNITY_PLATFORMS = {
    "linux.do": {
        "key": "linux-do",
        "feed_urls": ("https://linux.do/latest.rss",),
    },
    "v2ex.com": {
        "key": "v2ex",
        "feed_urls": ("https://www.v2ex.com/index.xml",),
    },
    "oschina.net": {
        "key": "oschina",
        "feed_urls": ("https://www.oschina.net/news/rss",),
    },
    "infoq.cn": {
        "key": "infoq-cn",
        "feed_urls": (
            "https://rsshub.rssforever.com/infoq/recommend",
            "https://hub.slarker.me/infoq/recommend",
            "https://rsshub.app/infoq/recommend",
        ),
    },
    "juejin.cn": {
        "key": "juejin",
        "feed_urls": (),
    },
}


def community_platform_key(url: str) -> str | None:
    host = urlparse(url.strip()).netloc.casefold().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    platform = COMMUNITY_PLATFORMS.get(host)
    return str(platform["key"]) if platform else None


def community_feed_url(url: str) -> str:
    return community_feed_urls(url)[0]


def community_feed_urls(url: str) -> tuple[str, ...]:
    host = urlparse(url.strip()).netloc.casefold().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    platform = COMMUNITY_PLATFORMS.get(host)
    if platform is None:
        raise ValueError(
            "暂不支持这个社区页面。当前支持 LINUX DO、V2EX、"
            "OSCHINA、InfoQ 中文和稀土掘金。"
        )
    return tuple(str(value) for value in platform["feed_urls"])


class CommunityCollector:
    """Resolve a community homepage to its maintained feed endpoint."""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url.strip()

    def collect(self):
        platform_key = community_platform_key(self.url)
        if platform_key == "juejin":
            yield from JuejinCollector(self.name).collect()
            return
        for feed_url in community_feed_urls(self.url):
            items = list(RSSCollector(self.name, feed_url).collect())
            if items:
                yield from items
                return
