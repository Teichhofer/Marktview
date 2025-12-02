import asyncio
from unittest.mock import AsyncMock

import pytest

from marktview import page_actions


class FakeButton:
    def __init__(self, visible=True):
        self.visible = visible
        self.clicked = False

    async def is_visible(self, timeout=None):  # noqa: ARG002
        return self.visible

    async def click(self):
        self.clicked = True


class FakeButtonLocator:
    def __init__(self, buttons):
        self._buttons = buttons

    async def count(self):
        return len(self._buttons)

    def nth(self, index):
        return self._buttons[index]


class FakePage:
    def __init__(self, cookie_buttons=None, age_button=None):
        self.cookie_buttons = cookie_buttons or []
        self.age_button = age_button
        self.waits = []

    def get_by_role(self, *_, **__):
        return FakeButtonLocator(self.cookie_buttons)

    def locator(self, *_):
        return self.age_button

    async def wait_for_load_state(self, state):  # noqa: ARG002
        self.waits.append(state)


@pytest.mark.asyncio
async def test_accept_cookies_clicks_first_visible():
    first = FakeButton(visible=True)
    page = FakePage(cookie_buttons=[first, FakeButton(visible=True)])

    await page_actions.accept_cookies(page)
    assert first.clicked is True


@pytest.mark.asyncio
async def test_accept_cookies_handles_exception():
    class ErrPage:
        def get_by_role(self, *_, **__):  # noqa: ANN001
            raise RuntimeError("fail")

    await page_actions.accept_cookies(ErrPage())


@pytest.mark.asyncio
async def test_confirm_age_handles_absent_button():
    page = FakePage(age_button=FakeButton(visible=False))
    await page_actions.confirm_age(page)
    assert page.age_button.clicked is False


@pytest.mark.asyncio
async def test_confirm_age_clicks_when_visible():
    button = FakeButton(visible=True)
    page = FakePage(age_button=button)
    await page_actions.confirm_age(page)
    assert button.clicked is True


@pytest.mark.asyncio
async def test_confirm_age_handles_exception():
    class ErrPage:
        def locator(self, *_):  # noqa: ANN001
            raise RuntimeError("broken")

    await page_actions.confirm_age(ErrPage())


@pytest.mark.asyncio
async def test_wait_for_page_ready_uses_jitter(monkeypatch):
    sleep_called = False

    async def fake_sleep(delay):
        nonlocal sleep_called
        sleep_called = True
        assert 0.1 <= delay <= 3.0

    monkeypatch.setattr(page_actions.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(page_actions.random, "uniform", lambda *_: 0.5)

    page = FakePage()
    await page_actions.wait_for_page_ready(page, delay=0.5)
    assert "networkidle" in page.waits
    assert sleep_called
