import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from marktview import cli, config
from marktview.models import Listing


class DummyBrowser:
    def __init__(self, context):
        self.context = context
        self.closed = False

    async def new_context(self):
        return self.context

    async def close(self):
        self.closed = True


class DummyPlaywright:
    def __init__(self, browser):
        self.chromium = SimpleNamespace(launch=lambda headless: asyncio.sleep(0, result=browser))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class DummyContext:
    def __init__(self, listings):
        self.listings = listings

    async def new_page(self):
        return None


@pytest.mark.asyncio
async def test_run_once_writes_results(monkeypatch, tmp_path):
    listings = [Listing(title="A", url="https://example.com")]
    context = DummyContext(listings)
    browser = DummyBrowser(context)
    playwright = DummyPlaywright(browser)

    args = SimpleNamespace(
        output=tmp_path / "out.xlsx",
        start_url="https://start",
        max_pages=1,
        concurrency=1,
        headless=True,
    )

    monkeypatch.setattr(cli, "async_playwright", lambda: playwright)
    monkeypatch.setattr(cli, "load_existing_listing_ids", lambda path: set())
    monkeypatch.setattr(
        cli,
        "scrape_pages",
        lambda *a, **k: asyncio.sleep(0, result=listings),
    )
    output = await cli.run_once(args)
    assert output.exists()


def test_configure_utf8_output_handles_missing_reconfigure(monkeypatch):
    stream = SimpleNamespace()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)
    cli.configure_utf8_output()


def test_clear_artifacts(tmp_path):
    output_path = tmp_path / "file.txt"
    output_path.write_text("data")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "a.log").write_text("log")

    cli.clear_artifacts(output_path, log_dir)
    assert not output_path.exists()
    assert not log_dir.exists()


def test_build_parser_defaults():
    parser = cli.build_parser()
    args = parser.parse_args([])
    assert args.start_url == config.START_URL
    assert args.max_pages == config.MAX_PAGES


def test_parse_args_uses_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog"])
    args = cli.parse_args()
    assert args.output == config.OUTPUT_FILE


def test_main_clear(monkeypatch, tmp_path):
    called = {}
    args = SimpleNamespace(
        start_url="https://example.com",
        output=tmp_path / "out.xlsx",
        max_pages=1,
        concurrency=1,
        headless=True,
        loop=False,
        clear=True,
    )

    monkeypatch.setattr(cli, "parse_args", lambda: args)
    monkeypatch.setattr(cli, "configure_utf8_output", lambda: called.setdefault("utf8", True))
    monkeypatch.setattr(cli, "configure_llm_logging", lambda log_dir: called.setdefault("llm", log_dir))
    monkeypatch.setattr(cli, "clear_artifacts", lambda output, log_dir: called.setdefault("cleared", (output, log_dir)))

    cli.main()

    assert "cleared" in called


def test_main_runs_once(monkeypatch, tmp_path):
    called = {}
    args = SimpleNamespace(
        start_url="https://example.com",
        output=tmp_path / "out.xlsx",
        max_pages=1,
        concurrency=1,
        headless=True,
        loop=False,
        clear=False,
    )

    monkeypatch.setattr(cli, "parse_args", lambda: args)
    monkeypatch.setattr(cli, "configure_utf8_output", lambda: None)
    monkeypatch.setattr(cli, "configure_llm_logging", lambda log_dir: called.setdefault("llm", log_dir))
    monkeypatch.setattr(cli.logging, "basicConfig", lambda **kwargs: called.setdefault("logging", kwargs))
    monkeypatch.setattr(cli, "run_once", lambda args: "done")
    monkeypatch.setattr(cli.asyncio, "run", lambda coro: called.setdefault("ran", coro))

    cli.main()

    assert called["ran"] == "done"
