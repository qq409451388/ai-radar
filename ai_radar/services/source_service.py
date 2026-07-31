"""Configuration lifecycle for information sources."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_radar.models import SourceConfig, SourceItem


class SourceService:
    """Edit and remove source configurations with predictable side effects."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def update(
        self,
        source_config_id: int,
        *,
        name: str,
        source_type: str,
        url: str,
        repository: str,
        path_filter: str,
        default_topic_id: int | None,
    ) -> dict:
        source = self.session.get(SourceConfig, source_config_id)
        if source is None:
            raise ValueError(f"source_config {source_config_id} not found")

        connection_changed = any(
            (
                source.source_type != source_type,
                source.url != url,
                source.repository != repository,
                source.path_filter != path_filter,
            )
        )
        source.name = name
        source.source_type = source_type
        source.url = url
        source.repository = repository
        source.path_filter = path_filter
        source.default_topic_id = default_topic_id

        if connection_changed:
            source.enabled = False
            source.test_status = "UNTESTED"
            source.last_tested_at = None
            source.last_error = ""

        self.session.flush()
        return {
            "source_config_id": source.id,
            "source": source.name,
            "connection_changed": connection_changed,
        }

    def delete(self, source_config_id: int) -> dict:
        source = self.session.get(SourceConfig, source_config_id)
        if source is None:
            raise ValueError(f"source_config {source_config_id} not found")
        item_count = self.item_count(source_config_id)
        result = {
            "source_config_id": source.id,
            "source": source.name,
            "deleted_items": item_count,
        }
        self.session.delete(source)
        self.session.flush()
        return result

    def item_count(self, source_config_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count(SourceItem.id)).where(
                    SourceItem.source_config_id == source_config_id
                )
            )
            or 0
        )
