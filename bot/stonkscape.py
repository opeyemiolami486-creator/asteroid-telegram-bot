from __future__ import annotations

"""Adapter for an authorized StonkScape gameplay bridge.

The public StonkScape page is a WebAssembly client that speaks a binary game
protocol over a WebSocket. It does not expose a documented JSON API. This
module therefore defines a small, testable bridge contract instead of
pretending that `/rs2.cgi` accepts REST actions. A browser worker or an
organizer-provided harness can implement this contract while the Telegram bot
remains focused on orchestration and policy.
"""

from typing import Any
from urllib.parse import urlencode

import httpx

from .models import ActionName, GameState, UserState
from .game_adapter import GameAdapter


class StonkScapeBridgeAdapter(GameAdapter):
    """Drive StonkScape through an explicitly authorized JSON bridge.

    Bridge endpoints:
      POST /play-code  -> {"play_code": "..."}
      POST /session    -> {"session_id": "..."}
      GET  /state      -> a GameState-shaped object (or {"state": {...}})
      POST /action     -> a GameState-shaped object (or {"state": {...}})
      POST /upgrade    -> a GameState-shaped object (or {"state": {...}})

    Every request includes `play_code` and `session_id` where available. The
    reference game URL is metadata only; the bridge is the component that is
    allowed to automate the organizer's test harness.
    """

    def __init__(self, bridge_url: str, reference_url: str, timeout: float = 15.0) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self.reference_url = reference_url.rstrip("/")
        self.timeout = timeout
        self._authenticated: set[int] = set()

    async def login(self, user: UserState, username: str, password: str) -> None:
        if not username.strip() or not password:
            raise ValueError("game username and password are required")
        await self._request("POST", "/login", user, username=username.strip(), password=password)
        # The password is not retained after the bridge accepts it. Only an
        # in-memory authenticated marker remains; no password reaches state,
        # logs, or Telegram replies.
        self._authenticated.add(user.telegram_user_id)
        user.game_username = username.strip()

    async def _request(self, method: str, path: str, user: UserState, **payload: Any) -> dict[str, Any]:
        body = {"telegram_user_id": user.telegram_user_id, "reference_url": self.reference_url, **payload}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method == "GET":
                    response = await client.request(method, f"{self.bridge_url}{path}?{urlencode(body)}")
                else:
                    response = await client.request(method, f"{self.bridge_url}{path}", json=body)
                response.raise_for_status()
                result = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"StonkScape bridge request failed: {exc}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("StonkScape bridge returned a non-object response")
        if result.get("error"):
            raise RuntimeError(f"StonkScape bridge: {result['error']}")
        return result

    @staticmethod
    def _state(payload: dict[str, Any]) -> GameState:
        raw = payload.get("state", payload)
        if not isinstance(raw, dict):
            raise RuntimeError("StonkScape bridge returned an invalid state")
        return GameState(
            score=int(raw.get("score", 0) or 0),
            resources={str(k): int(v or 0) for k, v in (raw.get("resources", {}) or {}).items()},
            position={str(k): float(v or 0) for k, v in (raw.get("position", {}) or {}).items()},
            ship=str(raw.get("ship", "unknown")),
            rank=int(raw.get("rank", 0) or 0),
            upgrades={str(k): int(v or 0) for k, v in (raw.get("upgrades", {}) or {}).items()},
            cooldown_seconds=float(raw.get("cooldown_seconds", 0) or 0),
            alive=bool(raw.get("alive", True)),
            game_over=bool(raw.get("game_over", False)),
            raw=raw,
        )

    async def request_play_code(self, user: UserState) -> str:
        if user.telegram_user_id not in self._authenticated:
            raise RuntimeError("Log in first with /login <game_username> <game_password>")
        result = await self._request("POST", "/play-code", user)
        code = str(result.get("play_code", "")).strip()
        if not code:
            raise RuntimeError("StonkScape bridge did not return a unique play_code")
        return code

    async def start_session(self, user: UserState, play_code: str) -> str:
        result = await self._request("POST", "/session", user, play_code=play_code)
        session_id = str(result.get("session_id", "")).strip()
        if not session_id:
            raise RuntimeError("StonkScape bridge did not return a session_id")
        return session_id

    async def read_state(self, user: UserState) -> GameState:
        return self._state(await self._request("GET", "/state", user, play_code=user.play_code, session_id=user.session_id))

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        return self._state(await self._request("POST", "/action", user, play_code=user.play_code, session_id=user.session_id, action=action))

    async def upgrade(self, user: UserState) -> GameState:
        return self._state(await self._request("POST", "/upgrade", user, play_code=user.play_code, session_id=user.session_id))

    async def restart_session(self, user: UserState) -> str | None:
        if not user.play_code:
            return None
        return await self.start_session(user, user.play_code)
