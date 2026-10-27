from mcp_server import news


def test_unwritable_cache_still_returns_fresh_data(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    monkeypatch.setattr(news, "CACHE_DIR", blocker / "news")
    assert news._cached("articles", lambda: [{"title": "x"}]) == [{"title": "x"}]
