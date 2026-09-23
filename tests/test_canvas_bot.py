import asyncio

import pytest

from bot.canvas_bot import CanvasBot, CanvasBotConfig, CanvasTarget


class FakeMouse:
    def __init__(self, page):
        self.page = page
        self.clicks = []

    async def click(self, x, y):
        self.clicks.append((x, y))
        self.page.remaining = [target for target in self.page.remaining if abs(target.x - x) > 0.1 or abs(target.y - y) > 0.1]
        self.page.score += 100


class FakeCanvasPage:
    def __init__(self, targets):
        self.remaining = list(targets)
        self.score = 0
        self.mouse = FakeMouse(self)

    async def evaluate(self, expression, arg=None):
        if "document.querySelector(selector)" in expression and "c.width" in expression:
            return {"width": 800, "height": 500}
        if "getImageData" in expression:
            return [target.__dict__ for target in self.remaining]
        raise AssertionError(f"unexpected browser expression: {expression[:80]}")


@pytest.mark.asyncio
async def test_canvas_bot_aims_at_high_value_target_first_and_reaches_high_score():
    page = FakeCanvasPage(
        [
            CanvasTarget(120, 100, value=1),
            CanvasTarget(640, 250, value=10),
            CanvasTarget(400, 380, value=4),
        ]
    )
    bot = CanvasBot(CanvasBotConfig(max_shots=10, max_runtime_seconds=1, shot_interval_seconds=0))

    result = await bot.play(page)

    assert page.mouse.clicks[0] == (640, 250)
    assert result == {"shots_fired": 3, "targets_hit": 3}
    assert page.score == 300
    assert not page.remaining


def test_select_target_prefers_value_then_shortest_distance():
    targets = [CanvasTarget(100, 100, value=3), CanvasTarget(410, 260, value=3), CanvasTarget(300, 200, value=2)]

    selected = CanvasBot.select_target(targets, 800, 500)

    assert selected == targets[1]


def test_scan_script_is_present_and_canvas_only():
    from bot.canvas_bot import CANVAS_SCAN_SCRIPT

    assert "getImageData" in CANVAS_SCAN_SCRIPT
    assert "document.querySelector(selector)" in CANVAS_SCAN_SCRIPT
    assert "fetch(" not in CANVAS_SCAN_SCRIPT
    assert "WebSocket" not in CANVAS_SCAN_SCRIPT
