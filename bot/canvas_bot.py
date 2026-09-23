from __future__ import annotations

"""Opt-in canvas bot for an organizer-authorized browser test target.

The worker intentionally has no login, credential, or submission logic. A caller
must provide an already-authenticated browser page and an explicit canvas
selector. The page evaluates a small canvas reader in the game context, then the
worker clicks only at targets returned by that reader.
"""

from dataclasses import dataclass
import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


@dataclass(frozen=True)
class CanvasTarget:
    x: float
    y: float
    value: int = 1
    radius: float = 1.0


@dataclass(frozen=True)
class CanvasBotConfig:
    canvas_selector: str = "canvas"
    scan_interval_seconds: float = 0.08
    shot_interval_seconds: float = 0.12
    max_shots: int = 250
    max_runtime_seconds: float = 30.0
    target_min_saturation: float = 0.32
    target_min_brightness: float = 0.45
    target_max_brightness: float = 0.98
    edge_margin: int = 12
    hit_confirm_timeout_seconds: float = 0.35
    hit_confirm_poll_seconds: float = 0.04
    hit_confirm_radius_padding: float = 10.0


class BrowserPage(Protocol):
    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    @property
    def mouse(self) -> Any: ...


CANVAS_SCAN_SCRIPT = r"""
({selector, minSaturation, minBrightness, maxBrightness, edgeMargin}) => {
  const canvas = document.querySelector(selector);
  if (!canvas || canvas.width < 2 || canvas.height < 2) return [];
  const sample = document.createElement('canvas');
  const scale = Math.max(1, Math.ceil(Math.max(canvas.width, canvas.height) / 320));
  sample.width = Math.ceil(canvas.width / scale);
  sample.height = Math.ceil(canvas.height / scale);
  const ctx = sample.getContext('2d', {willReadFrequently: true});
  ctx.drawImage(canvas, 0, 0, sample.width, sample.height);
  const pixels = ctx.getImageData(0, 0, sample.width, sample.height).data;
  const seen = new Uint8Array(sample.width * sample.height);
  const points = [];
  const isTarget = (index, x, y) => {
    const r = pixels[index] / 255, g = pixels[index + 1] / 255;
    const b = pixels[index + 2] / 255, a = pixels[index + 3] / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const saturation = max === 0 ? 0 : (max - min) / max;
    return a > 0.5 && saturation >= minSaturation && max >= minBrightness &&
      max <= maxBrightness && x >= edgeMargin / scale && y >= edgeMargin / scale &&
      x < sample.width - edgeMargin / scale && y < sample.height - edgeMargin / scale;
  };
  const queue = [];
  for (let y = 0; y < sample.height; y += 2) for (let x = 0; x < sample.width; x += 2) {
    const start = y * sample.width + x;
    if (seen[start] || !isTarget(start * 4, x, y)) continue;
    seen[start] = 1; queue.length = 0; queue.push([x, y]);
    let sumX = 0, sumY = 0, count = 0, minX = x, maxX = x, minY = y, maxY = y;
    while (queue.length) {
      const [px, py] = queue.pop(); sumX += px; sumY += py; count++;
      minX = Math.min(minX, px); maxX = Math.max(maxX, px);
      minY = Math.min(minY, py); maxY = Math.max(maxY, py);
      for (const [nx, ny] of [[px + 2, py], [px - 2, py], [px, py + 2], [px, py - 2]]) {
        if (nx < 0 || ny < 0 || nx >= sample.width || ny >= sample.height) continue;
        const ni = ny * sample.width + nx;
        if (!seen[ni] && isTarget(ni * 4, nx, ny)) { seen[ni] = 1; queue.push([nx, ny]); }
      }
    }
    if (count >= 2) points.push({x: sumX / count * scale, y: sumY / count * scale,
      value: Math.max(1, Math.round(Math.min(99, count / 2))), radius: Math.max(1, Math.max(maxX - minX, maxY - minY) * scale / 2)});
  }
  return points;
})
"""


class CanvasBot:
    def __init__(self, config: CanvasBotConfig | None = None) -> None:
        self.config = config or CanvasBotConfig()
        self.shots_fired = 0
        self.targets_hit = 0

    @staticmethod
    def select_target(targets: list[CanvasTarget], width: float, height: float) -> CanvasTarget | None:
        if not targets:
            return None
        cx, cy = width / 2.0, height / 2.0
        return max(
            targets,
            key=lambda target: (
                target.value,
                -math.hypot(target.x - cx, target.y - cy),
            ),
        )

    async def scan(self, page: BrowserPage) -> list[CanvasTarget]:
        data = await page.evaluate(
            CANVAS_SCAN_SCRIPT,
            {
                "selector": self.config.canvas_selector,
                "minSaturation": self.config.target_min_saturation,
                "minBrightness": self.config.target_min_brightness,
                "maxBrightness": self.config.target_max_brightness,
                "edgeMargin": self.config.edge_margin,
            },
        )
        if not isinstance(data, list):
            return []
        targets: list[CanvasTarget] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                targets.append(CanvasTarget(float(item["x"]), float(item["y"]), int(item.get("value", 1)), float(item.get("radius", 1))))
            except (KeyError, TypeError, ValueError):
                continue
        return targets

    def _target_still_present(self, before: CanvasTarget, after: list[CanvasTarget]) -> bool:
        """Treat a target as unhit while a matching visual target remains."""
        return any(
            math.hypot(target.x - before.x, target.y - before.y)
            <= max(before.radius, target.radius) + self.config.hit_confirm_radius_padding
            for target in after
        )

    async def _confirm_hit(self, page: BrowserPage, target: CanvasTarget) -> bool:
        deadline = asyncio.get_running_loop().time() + self.config.hit_confirm_timeout_seconds
        while True:
            if not self._target_still_present(target, await self.scan(page)):
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self.config.hit_confirm_poll_seconds)

    async def play(
        self,
        page: BrowserPage,
        on_confirmed_hit: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, int]:
        """Run until the shot/runtime bound is reached or the canvas has no target.

        The browser page owns authentication and game lifecycle. This method is
        deliberately bounded so a test run cannot become an unmonitored loop.
        """
        started = asyncio.get_running_loop().time()
        while self.shots_fired < self.config.max_shots:
            if asyncio.get_running_loop().time() - started >= self.config.max_runtime_seconds:
                break
            frame = await page.evaluate(
                """selector => { const c = document.querySelector(selector); const r = c && c.getBoundingClientRect(); return c ? {width:c.width,height:c.height,cssWidth:r.width,cssHeight:r.height} : null; }""",
                self.config.canvas_selector,
            )
            if not isinstance(frame, dict) or not frame.get("width") or not frame.get("height"):
                break
            target = self.select_target(await self.scan(page), float(frame["width"]), float(frame["height"]))
            if target is None:
                await asyncio.sleep(self.config.scan_interval_seconds)
                continue
            css_width = float(frame.get("cssWidth") or frame["width"])
            css_height = float(frame.get("cssHeight") or frame["height"])
            await page.mouse.click(target.x * css_width / float(frame["width"]), target.y * css_height / float(frame["height"]))
            self.shots_fired += 1
            if await self._confirm_hit(page, target):
                self.targets_hit += 1
                if on_confirmed_hit is not None:
                    await on_confirmed_hit()
            await asyncio.sleep(self.config.shot_interval_seconds)
        return {"shots_fired": self.shots_fired, "targets_hit": self.targets_hit}


async def run_authorized_page(
    page: BrowserPage,
    config: CanvasBotConfig | None = None,
    on_confirmed_hit: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, int]:
    """Convenience entry point for a caller that already owns a browser session."""
    return await CanvasBot(config).play(page, on_confirmed_hit=on_confirmed_hit)


async def run_authorized_page_with_adapter(
    page: BrowserPage,
    adapter: Any,
    user: Any,
    config: CanvasBotConfig | None = None,
) -> dict[str, int]:
    """Play a logged-in page and report only canvas-confirmed kills to an adapter."""
    async def on_confirmed_hit() -> None:
        await adapter.record_observed_kill(user)

    return await CanvasBot(config).play(page, on_confirmed_hit=on_confirmed_hit)


__all__ = ["BrowserPage", "CanvasBot", "CanvasBotConfig", "CanvasTarget", "run_authorized_page", "run_authorized_page_with_adapter"]


if __name__ == "__main__":
    raise SystemExit("Import CanvasBot from an organizer-authorized browser worker; no live target is configured here.")
