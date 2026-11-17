from html.parser import HTMLParser

from fastapi.testclient import TestClient

import app.main
from app.main import create_app


def test_stock_screen_is_served():
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "CheckStock" in response.text


def test_asset_urls_change_when_frontend_files_change(tmp_path, monkeypatch):
    """An already-cached script must not be reused with a newer HTML page."""

    class Assets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "script":
                self.urls.append(attrs["src"])
            if tag == "link" and attrs.get("rel") == "stylesheet":
                self.urls.append(attrs["href"])

    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="/static/styles.css"><script src="/static/app.js"></script>'
    )
    for asset in ["styles.css", "app.js"]:
        (tmp_path / asset).write_text("/* first version */")
    monkeypatch.setattr(app.main, "STATIC", tmp_path)

    def load():
        with TestClient(create_app()) as client:
            response = client.get("/")
            assert response.headers["cache-control"] == "no-cache"
            parser = Assets()
            parser.feed(response.text)
            for url in parser.urls:
                assert client.get(url).status_code == 200
            return parser.urls

    before = load()
    for asset in ["styles.css", "app.js"]:
        (tmp_path / asset).write_text("/* updated version */")
    after = load()
    assert all(old != new for old, new in zip(before, after, strict=True))
