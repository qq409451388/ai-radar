"""Native collector for Juejin's public AI category feed."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ai_radar.collectors.base import CollectedItem
from ai_radar.config import get_config

JUEJIN_AI_CATEGORY_ID = "6809637773935378440"
JUEJIN_FEED_API = (
    "https://api.juejin.cn/recommend_api/v1/article/"
    "recommend_cate_feed?aid=2608&uuid=0&spider=0"
)


class JuejinCollector:
    """Collect article metadata directly instead of scraping the JS page."""

    def __init__(self, name: str) -> None:
        self.name = name

    def collect(self):
        with httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Radar/0.1)"},
            timeout=get_config().http_timeout,
            follow_redirects=True,
        ) as client:
            response = client.post(
                JUEJIN_FEED_API,
                json={
                    "id_type": 2,
                    "client_type": 2608,
                    "sort_type": 200,
                    "cursor": "0",
                    "limit": 20,
                    "cate_id": JUEJIN_AI_CATEGORY_ID,
                },
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("err_no") != 0:
            raise ValueError(
                payload.get("err_msg") or "掘金分类接口返回异常"
            )
        for record in payload.get("data") or []:
            info = record.get("article_info") or {}
            article_id = str(
                info.get("article_id") or record.get("article_id") or ""
            ).strip()
            title = str(info.get("title") or "").strip()
            brief = str(info.get("brief_content") or "").strip()
            if not article_id or not title:
                continue
            author_info = record.get("author_user_info") or {}
            yield CollectedItem(
                external_id=article_id,
                title=title,
                url=f"https://juejin.cn/post/{article_id}",
                author=str(author_info.get("user_name") or self.name),
                published_at=_from_timestamp(
                    info.get("rtime") or info.get("ctime")
                ),
                content=brief or title,
            )


def _from_timestamp(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
