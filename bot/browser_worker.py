from __future__ import annotations

"""Live PlanetForge browser worker.

The worker uses Playwright with a small in-page wallet-provider shim. The shim
exposes only the public address and delegates message signing back to the
Python Solana signer; the private seed never enters page JavaScript. CanvasBot
then clicks targets and reports only targets that disappear after a click.
"""

import shutil
import json
from typing import Any

from .canvas_bot import CanvasBot, CanvasBotConfig
from .models import UserState
from .wallet import SolanaSigner


WALLET_INIT_SCRIPT = r"""
(() => {
  const address = __PLANETFORGE_ADDRESS__;
  const publicKey = {
    toBase58: () => address,
    toString: () => address,
  };
  const provider = {
    isPhantom: true,
    publicKey,
    async connect() { return { publicKey }; },
    async disconnect() {},
    async signMessage(message) {
      const bytes = Array.from(message instanceof Uint8Array ? message : new Uint8Array(message));
      const signature = await window.__planetforgeSignMessage(bytes);
      return { signature: new Uint8Array(signature) };
    },
  };
  window.phantom = { solana: provider };
  window.solana = provider;
})();
"""


class LiveBrowserWorker:
    """Own one authenticated browser context per Telegram user."""

    def __init__(
        self,
        signer: SolanaSigner,
        game_url: str = "https://planet-forge.com",
        canvas_config: CanvasBotConfig | None = None,
        headless: bool = True,
        executable_path: str = "",
    ) -> None:
        self.signer = signer
        self.game_url = game_url.rstrip("/")
        self.canvas_config = canvas_config or CanvasBotConfig()
        self.headless = headless
        self.executable_path = executable_path or shutil.which("chromium") or shutil.which("google-chrome") or ""
        self._playwright: Any = None
        self._browser: Any = None
        self._contexts: dict[int, Any] = {}
        self._pages: dict[int, Any] = {}

    async def _ensure_runtime(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise RuntimeError("Live browser gameplay requires the playwright package") from exc
        self._playwright = await async_playwright().start()
        launch_args = {"headless": self.headless}
        if self.executable_path:
            launch_args["executable_path"] = self.executable_path
        self._browser = await self._playwright.chromium.launch(**launch_args)

    async def _new_context(self, user: UserState) -> tuple[Any, Any]:
        await self._ensure_runtime()
        context = await self._browser.new_context(viewport={"width": 1280, "height": 900})

        async def sign_message(_source: Any, message: list[int]) -> list[int]:
            try:
                return list(self.signer.sign(bytes(message)))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("PlanetForge wallet message was not byte data") from exc

        await context.expose_binding("__planetforgeSignMessage", sign_message)
        init_script = WALLET_INIT_SCRIPT.replace("__PLANETFORGE_ADDRESS__", json.dumps(self.signer.address))
        await context.add_init_script(init_script)
        page = await context.new_page()
        await page.goto(self.game_url, wait_until="domcontentloaded")
        await self._connect_wallet(page)
        return context, page

    async def _connect_wallet(self, page: Any) -> None:
        connect = page.get_by_role("button", name="CONNECT WALLET")
        if await connect.count():
            await connect.first.click()
            phantom = page.get_by_text("Phantom", exact=True)
            if await phantom.count():
                await phantom.first.click()
        try:
            await page.wait_for_selector("canvas", state="visible", timeout=15_000)
        except Exception as exc:
            body = await page.locator("body").inner_text()
            if "No Solana wallet detected" in body:
                raise RuntimeError("Injected wallet was not detected by PlanetForge") from exc
            raise RuntimeError("PlanetForge did not open a playable canvas after wallet connection") from exc

    async def _page_for(self, user: UserState) -> Any:
        page = self._pages.get(user.telegram_user_id)
        if page is not None and not page.is_closed():
            return page
        context, page = await self._new_context(user)
        self._contexts[user.telegram_user_id] = context
        self._pages[user.telegram_user_id] = page
        return page

    async def play(self, user: UserState, adapter: Any) -> dict[str, int]:
        """Run one bounded live canvas session and report confirmed kills."""
        page = await self._page_for(user)

        async def on_confirmed_hit() -> None:
            await adapter.record_observed_kill(user)

        result = await CanvasBot(self.canvas_config).play(page, on_confirmed_hit=on_confirmed_hit)
        return result

    async def close(self, user: UserState) -> None:
        user_id = user.telegram_user_id
        page = self._pages.pop(user_id, None)
        context = self._contexts.pop(user_id, None)
        if page is not None and not page.is_closed():
            await page.close()
        if context is not None:
            await context.close()

    async def close_all(self) -> None:
        for user_id in list(self._contexts):
            page = self._pages.pop(user_id, None)
            context = self._contexts.pop(user_id, None)
            if page is not None and not page.is_closed():
                await page.close()
            if context is not None:
                await context.close()
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


__all__ = ["LiveBrowserWorker", "WALLET_INIT_SCRIPT"]
