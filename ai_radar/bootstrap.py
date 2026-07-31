"""Constants, coverage coefficients and seed/bootstrap logic."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.config import PROJECT_ROOT
from ai_radar.collectors.community import community_platform_key
from ai_radar.models import (
    SourceConfig,
    Topic,
)

# ----- Coverage levels and coefficients (fixed mapping, section 八/十五) -----
COVERAGE_NONE = "NONE"
COVERAGE_AWARE = "AWARE"
COVERAGE_UNDERSTOOD = "UNDERSTOOD"
COVERAGE_PRACTICED = "PRACTICED"

COVERAGE_COEFFICIENTS: dict[str, float] = {
    COVERAGE_NONE: 0.00,
    COVERAGE_AWARE: 0.25,
    COVERAGE_UNDERSTOOD: 0.65,
    COVERAGE_PRACTICED: 1.00,
}

VALID_COVERAGE_LEVELS = set(COVERAGE_COEFFICIENTS.keys())

# ----- Importance levels (section 七.4) -----
IMPORTANCE_MINOR = 1
IMPORTANCE_NOTABLE = 3
IMPORTANCE_MAJOR = 5
VALID_IMPORTANCE = {IMPORTANCE_MINOR, IMPORTANCE_NOTABLE, IMPORTANCE_MAJOR}

# ----- Evidence types (section 七.7) -----
EVIDENCE_TYPES = {
    "DISCUSSION",
    "RESEARCH",
    "DESIGN",
    "DEMO",
    "IMPLEMENTATION",
    "PRODUCTION",
    "DECISION",
}

# ----- Source types -----
SOURCE_TYPE_RSS = "RSS"
SOURCE_TYPE_WEB_PAGE = "WEB_PAGE"
SOURCE_TYPE_GITHUB_RELEASE = "GITHUB_RELEASE"
SOURCE_TYPE_GITHUB_COMMIT = "GITHUB_COMMIT"
SOURCE_TYPE_COMMUNITY = "COMMUNITY"

SOURCE_KIND_OFFICIAL = "OFFICIAL"
SOURCE_KIND_COMMUNITY = "COMMUNITY"


def source_kind(source_type: str) -> str:
    return (
        SOURCE_KIND_COMMUNITY
        if source_type == SOURCE_TYPE_COMMUNITY
        else SOURCE_KIND_OFFICIAL
    )


def source_kind_label(source_type: str) -> str:
    return "社区讨论" if source_kind(source_type) == SOURCE_KIND_COMMUNITY else "官方来源"

# ----- Intelligence signal types -----
SIGNAL_RELEASE = "RELEASE"
SIGNAL_CAPABILITY = "CAPABILITY"
SIGNAL_CONCEPT = "CONCEPT"
SIGNAL_ARCHITECTURE = "ARCHITECTURE"
SIGNAL_STANDARD = "STANDARD"
VALID_SIGNAL_TYPES = {
    SIGNAL_RELEASE,
    SIGNAL_CAPABILITY,
    SIGNAL_CONCEPT,
    SIGNAL_ARCHITECTURE,
    SIGNAL_STANDARD,
}
DESIGN_SIGNAL_TYPES = {
    SIGNAL_CONCEPT,
    SIGNAL_ARCHITECTURE,
    SIGNAL_STANDARD,
}
SIGNAL_PRIORITY = {
    SIGNAL_RELEASE: 1,
    SIGNAL_CAPABILITY: 2,
    SIGNAL_CONCEPT: 3,
    SIGNAL_ARCHITECTURE: 4,
    SIGNAL_STANDARD: 5,
}

# ----- Statuses -----
STATUS_ACTIVE = "ACTIVE"
STATUS_DEPRECATED = "DEPRECATED"

ANALYZE_PENDING = "PENDING"
ANALYZE_SUCCESS = "SUCCESS"
ANALYZE_FAILED = "FAILED"
ANALYZE_IGNORED = "IGNORED"

SYNC_SUCCESS = "SUCCESS"
SYNC_FAILED = "FAILED"

# ----- Job types -----
JOB_COLLECT = "collect_sources"
JOB_ANALYZE = "analyze_items"
JOB_SYNC_PROFILE = "sync_profile"
JOB_EXTRACT_FACTS = "extract_facts"
JOB_ASSESS_NEW = "assess_new_change_points"
JOB_ASSESS_ALL = "assess_all_change_points"
JOB_RESCORE = "rescore"
JOB_SNAPSHOT = "snapshot"
JOB_MERGE = "merge_change_points"

DEFAULT_SOURCES_PATH = PROJECT_ROOT / "config" / "default_sources.yaml"


def load_default_sources_yaml(path: Path = DEFAULT_SOURCES_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def seed_default_data(session: Session, force: bool = False) -> dict:
    """Seed initial topics and sources if the DB is empty.

    Returns a dict with counts of created topics/sources.
    """
    created = {"topics": 0, "sources": 0}

    data = load_default_sources_yaml()
    if not data:
        return created

    # ----- Topics -----
    existing_topic_names = {
        row[0] for row in session.execute(select(Topic.name)).all()
    }
    topic_name_to_id: dict[str, int] = {
        row.name: row.id for row in session.execute(select(Topic)).scalars()
    }

    for topic_def in data.get("initial_topics", []):
        name = topic_def["name"]
        if name in existing_topic_names:
            continue
        topic = Topic(name=name, description=topic_def.get("description", ""))
        session.add(topic)
        session.flush()
        topic_name_to_id[name] = topic.id
        existing_topic_names.add(name)
        created["topics"] += 1

    # ----- RSS sources -----
    existing_sources = list(session.execute(select(SourceConfig)).scalars())
    existing_source_keys = {
        (row.source_type, row.url) for row in existing_sources
    }

    def _resolve_topic_id(name: str) -> int | None:
        return topic_name_to_id.get(name)

    for rss in data.get("rss_sources", []):
        key = (SOURCE_TYPE_RSS, rss["url"])
        if key in existing_source_keys:
            continue
        topic_id = _resolve_topic_id(rss.get("default_topic", ""))
        sc = SourceConfig(
            name=rss["name"],
            source_type=SOURCE_TYPE_RSS,
            url=rss["url"],
            repository="",
            path_filter="",
            enabled=bool(rss.get("enabled", False)),
            test_status=(
                "PASSED" if bool(rss.get("enabled", False)) else "UNTESTED"
            ),
            default_topic_id=topic_id,
        )
        session.add(sc)
        existing_source_keys.add(key)
        created["sources"] += 1

    # ----- Official web article indexes / watched pages -----
    for page in data.get("web_page_sources", []):
        key = (SOURCE_TYPE_WEB_PAGE, page["url"])
        if key in existing_source_keys:
            continue
        topic_id = _resolve_topic_id(page.get("default_topic", ""))
        session.add(
            SourceConfig(
                name=page["name"],
                source_type=SOURCE_TYPE_WEB_PAGE,
                url=page["url"],
                repository="",
                path_filter=page.get("path_filter", ""),
                enabled=bool(page.get("enabled", False)),
                test_status=(
                    "PASSED" if bool(page.get("enabled", False)) else "UNTESTED"
                ),
                default_topic_id=topic_id,
            )
        )
        existing_source_keys.add(key)
        created["sources"] += 1

    # ----- Developer community discussions -----
    for community in data.get("community_sources", []):
        platform_key = community_platform_key(community["url"])
        existing = next(
            (
                source
                for source in existing_sources
                if platform_key
                and community_platform_key(source.url) == platform_key
            ),
            None,
        )
        if existing is not None:
            # Migrate old RSS/web configurations such as juejin.cn/ai to the
            # dedicated adapter. A new test is required because the connection
            # method changed.
            if existing.source_type != SOURCE_TYPE_COMMUNITY:
                existing_source_keys.discard(
                    (existing.source_type, existing.url)
                )
                existing.source_type = SOURCE_TYPE_COMMUNITY
                existing.enabled = False
                existing.test_status = "UNTESTED"
                existing.last_tested_at = None
                existing.last_error = ""
                existing_source_keys.add(
                    (existing.source_type, existing.url)
                )
            continue
        key = (SOURCE_TYPE_COMMUNITY, community["url"])
        if key in existing_source_keys:
            continue
        topic_id = _resolve_topic_id(community.get("default_topic", ""))
        source = SourceConfig(
            name=community["name"],
            source_type=SOURCE_TYPE_COMMUNITY,
            url=community["url"],
            repository="",
            path_filter="",
            enabled=False,
            test_status="UNTESTED",
            default_topic_id=topic_id,
        )
        session.add(source)
        existing_sources.append(source)
        existing_source_keys.add(key)
        created["sources"] += 1

    # ----- GitHub release sources -----
    for gh in data.get("github_release_sources", []):
        key = (SOURCE_TYPE_GITHUB_RELEASE, gh["url"])
        if key in existing_source_keys:
            continue
        topic_id = _resolve_topic_id(gh.get("default_topic", ""))
        sc = SourceConfig(
            name=gh["name"],
            source_type=SOURCE_TYPE_GITHUB_RELEASE,
            url=gh["url"],
            repository=gh.get("repository", ""),
            path_filter="",
            enabled=bool(gh.get("enabled", False)),
            test_status=(
                "PASSED" if bool(gh.get("enabled", False)) else "UNTESTED"
            ),
            default_topic_id=topic_id,
        )
        session.add(sc)
        existing_source_keys.add(key)
        created["sources"] += 1

    # ----- GitHub specification/document commit sources -----
    for gh in data.get("github_commit_sources", []):
        key = (SOURCE_TYPE_GITHUB_COMMIT, gh["url"])
        if key in existing_source_keys:
            continue
        topic_id = _resolve_topic_id(gh.get("default_topic", ""))
        session.add(
            SourceConfig(
                name=gh["name"],
                source_type=SOURCE_TYPE_GITHUB_COMMIT,
                url=gh["url"],
                repository=gh.get("repository", ""),
                path_filter=gh.get("path_filter", ""),
                enabled=bool(gh.get("enabled", False)),
                test_status=(
                    "PASSED" if bool(gh.get("enabled", False)) else "UNTESTED"
                ),
                default_topic_id=topic_id,
            )
        )
        existing_source_keys.add(key)
        created["sources"] += 1

    session.flush()
    return created


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
