from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import select

from ai_radar.bootstrap import (
    SOURCE_TYPE_COMMUNITY,
    load_default_sources_yaml,
    seed_default_data,
)
from ai_radar.collectors.community import community_feed_url
from ai_radar.collectors.github_commit import GitHubCommitCollector
from ai_radar.collectors.juejin import JuejinCollector
from ai_radar.collectors.web_page import (
    WebPageCollector,
    _article_links,
    _parse_html,
)
from ai_radar.models import SourceConfig


class _Response:
    def __init__(self, *, text: str = "", data=None) -> None:
        self.text = text
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._data


def test_default_sources_watch_engineering_and_spec_changes():
    data = load_default_sources_yaml()

    assert any(
        source["name"] == "Anthropic Engineering"
        and source["enabled"] is True
        for source in data["web_page_sources"]
    )
    repositories = {
        source["repository"] for source in data["github_commit_sources"]
    }
    assert "anthropics/skills" in repositories
    assert "modelcontextprotocol/modelcontextprotocol" in repositories


def test_design_sources_are_seeded_with_filters(seeded_session):
    sources = {
        source.name: source
        for source in seeded_session.execute(select(SourceConfig)).scalars()
    }

    assert sources["Anthropic Engineering"].source_type == "WEB_PAGE"
    assert sources["Anthropic Engineering"].is_builtin is True
    assert sources["Anthropic Engineering"].path_filter == "/engineering/"
    assert sources["Agent Skills Specification"].source_type == "GITHUB_COMMIT"
    assert sources["Agent Skills Specification"].path_filter == "spec"
    assert sources["MCP Specification"].path_filter == "schema"


def test_default_developer_communities_are_seeded_as_unverified_discussions(
    seeded_session,
):
    sources = {
        source.name: source
        for source in seeded_session.execute(select(SourceConfig)).scalars()
    }

    expected = {
        "LINUX DO",
        "V2EX",
        "开源中国 OSCHINA",
        "InfoQ 中文",
        "稀土掘金",
    }
    assert expected.issubset(sources)
    for name in expected:
        assert sources[name].source_type == SOURCE_TYPE_COMMUNITY
        assert sources[name].is_builtin is True
        assert sources[name].enabled is False
        assert sources[name].test_status == "UNTESTED"


def test_existing_juejin_page_is_migrated_to_community_adapter(session):
    old_source = SourceConfig(
        name="掘金AI",
        source_type="RSS",
        url="https://juejin.cn/ai",
        enabled=True,
        test_status="PASSED",
    )
    session.add(old_source)
    session.flush()

    seed_default_data(session)

    assert old_source.source_type == SOURCE_TYPE_COMMUNITY
    assert old_source.is_builtin is True
    assert old_source.enabled is False
    assert old_source.test_status == "UNTESTED"


def test_supported_community_pages_resolve_to_collection_feeds():
    assert community_feed_url("https://linux.do/") == (
        "https://linux.do/latest.rss"
    )
    assert community_feed_url("https://www.v2ex.com/") == (
        "https://www.v2ex.com/index.xml"
    )
    assert community_feed_url("https://www.oschina.net/") == (
        "https://www.oschina.net/news/rss"
    )
    assert community_feed_url("https://www.infoq.cn/") == (
        "https://rsshub.rssforever.com/infoq/recommend"
    )


def test_juejin_collector_uses_ai_category_api(monkeypatch):
    payload = {
        "err_no": 0,
        "data": [
            {
                "article_id": "123",
                "article_info": {
                    "article_id": "123",
                    "title": "Codex 实战",
                    "brief_content": "一篇社区工具实测。",
                    "rtime": "1785480000",
                },
                "author_user_info": {"user_name": "测试作者"},
            }
        ],
    }

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url: str, *, json: dict):
            assert "recommend_cate_feed" in url
            assert json["cate_id"] == "6809637773935378440"
            return _Response(data=payload)

    monkeypatch.setattr(
        "ai_radar.collectors.juejin.httpx.Client",
        _Client,
    )
    items = list(JuejinCollector("稀土掘金").collect())

    assert len(items) == 1
    assert items[0].external_id == "123"
    assert items[0].title == "Codex 实战"
    assert items[0].url == "https://juejin.cn/post/123"
    assert items[0].author == "测试作者"
    assert items[0].content == "一篇社区工具实测。"


def test_web_page_parser_discovers_only_matching_same_host_articles():
    parsed = _parse_html(
        """
        <html><head>
          <title>Engineering</title>
          <meta property="article:published_time" content="2026-07-30T10:00:00Z">
        </head><body>
          <a href="/engineering/new-agent-pattern">New pattern</a>
          <a href="/news/company">Company news</a>
          <a href="https://example.org/engineering/external">External</a>
        </body></html>
        """
    )

    assert parsed.title == "Engineering"
    assert parsed.published_at == "2026-07-30T10:00:00Z"
    assert _article_links(
        "https://example.com/engineering",
        parsed.links,
        "/engineering/",
    ) == ["https://example.com/engineering/new-agent-pattern"]


def test_web_page_collector_fetches_discovered_article(monkeypatch):
    index = _Response(
        text='<a href="/engineering/skills">Agent Skills</a>'
    )
    article = _Response(
        text=(
            "<html><head><title>Agent Skills</title>"
            '<time datetime="2025-10-16"></time></head>'
            "<body><h1>Agent Skills</h1><p>Composable instructions and scripts.</p></body></html>"
        )
    )

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str):
            return article if url.endswith("/skills") else index

    monkeypatch.setattr("ai_radar.collectors.web_page.httpx.Client", _Client)
    items = list(
        WebPageCollector(
            "Engineering",
            "https://example.com/engineering",
            "/engineering/",
        ).collect()
    )

    assert len(items) == 1
    assert items[0].title == "Agent Skills"
    assert items[0].url == "https://example.com/engineering/skills"
    assert "Composable instructions" in items[0].content


def test_github_commit_collector_includes_watched_patch():
    commit_row = {
        "sha": "abc123",
        "html_url": "https://github.com/o/r/commit/abc123",
        "commit": {
            "message": "spec: introduce capability negotiation",
            "author": {"name": "Maintainer", "date": "2026-07-30T10:00:00Z"},
        },
    }
    list_response = _Response(data=[commit_row])
    detail_response = _Response(
        data={
            "files": [
                {
                    "filename": "spec/protocol.md",
                    "status": "modified",
                    "patch": "+ Capability negotiation",
                },
                {
                    "filename": "README.md",
                    "status": "modified",
                    "patch": "+ unrelated",
                },
            ]
        }
    )

    with patch(
        "ai_radar.collectors.github_commit.httpx.get",
        side_effect=[list_response, detail_response],
    ):
        items = list(GitHubCommitCollector("Spec", "o/r", "spec").collect())

    assert len(items) == 1
    assert items[0].external_id == "abc123"
    assert "spec/protocol.md" in items[0].content
    assert "README.md" not in items[0].content
