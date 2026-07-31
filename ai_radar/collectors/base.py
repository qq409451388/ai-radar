"""Base collector interface shared by RSS and GitHub Release collectors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol


@dataclass
class CollectedItem:
    """A normalized item produced by any collector."""

    external_id: str
    title: str
    url: str
    author: str
    published_at: datetime | None
    content: str  # raw body / summary used for hashing and analysis

    @property
    def content_hash(self) -> str:
        from ai_radar.utils import sha256_hex

        return sha256_hex(self.content.strip())


class Collector(Protocol):
    name: str

    def collect(self) -> Iterable[CollectedItem]:  # pragma: no cover - protocol
        ...
