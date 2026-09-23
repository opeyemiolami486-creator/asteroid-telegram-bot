from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import random
from urllib.parse import urlparse

import httpx

from .models import ActionName, GameState, UserState


class GameAdapter(ABC):
    @abstractmethod
    async def request_play_code(self, user: UserState) -> str:
        raise NotImplementedError

    @abstractmethod
    async def start_session(self, user: UserState, play_code: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def read_state(self, user: UserState) -> GameState:
        raise NotImplementedError

    @abstractmethod
    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        raise NotImplementedError

    @abstractmethod
    async def upgrade(self, user: UserState) -> GameState:
        raise NotImplementedError


def normalize_target(value: str) -> str:
    """Validate a user-selected test target and return a canonical value."""
    target = value.strip()
    if target.lower() in {"demo", "local", "offline"}:
        return "demo"
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("target must be 'demo' or an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("target URLs must not contain credentials")
    return target.rstrip("/")


class ExternalJsonGameAdapter(GameAdapter):
    """Adapter for an authorized JSON test harness with a small documented contract.

    Endpoints are relative to ``base_url``. The harness should return JSON containing
    ``play_code`` from POST play-code, ``session_id`` from POST session, and a game
    state object from GET state and POST action. State fields match GameState; unknown
    fields are preserved in ``raw``. The session ID is sent as a ``session_id`` query
    parameter for GET state and in the JSON body for POST action.
    """

    def __init__(
        self,
        base_url: str,
        play_code_path: str = "/api/play-code",
        session_path: str = "/api/session",
        state_path: str = "/api/state",
        action_path: str = "/api/action",
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = normalize_target(base_url)
        if self.base_url == "demo":
            raise ValueError("external adapter requires an http(s) URL")
        self.play_code_path = play_code_path
        self.session_path = session_path
        self.state_path = state_path
        self.action_path = action_path
        self.timeout_seconds = timeout_seconds

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.request(method, self._url(path), **kwargs)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"{method} {path} returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"could not reach external target {self.base_url}: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "unknown")
            raise RuntimeError(
                f"{method} {path} returned non-JSON content ({content_type}); "
                "check the endpoint paths and test-harness contract"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} must return a JSON object")
        return payload

    @staticmethod
    def _required(payload: dict, *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value):
                return str(value)
        raise RuntimeError(f"external target response is missing one of: {', '.join(keys)}")

    @staticmethod
    def _state(payload: dict) -> GameState:
        data = payload.get("state", payload)
        if not isinstance(data, dict):
            raise RuntimeError("external target state response must contain a JSON object")
        known = {"score", "resources", "position", "ship", "rank", "upgrades", "cooldown_seconds", "alive", "game_over"}
        return GameState(
            score=int(data.get("score", 0)),
            resources=dict(data.get("resources", {})),
            position=dict(data.get("position", {})),
            ship=str(data.get("ship", "unknown")),
            rank=int(data.get("rank", 0)),
            upgrades=dict(data.get("upgrades", {})),
            cooldown_seconds=float(data.get("cooldown_seconds", 0.0)),
            alive=bool(data.get("alive", True)),
            game_over=bool(data.get("game_over", False)),
            raw={key: value for key, value in data.items() if key not in known},
        )

    async def request_play_code(self, user: UserState) -> str:
        payload = await self._request(
            "POST",
            self.play_code_path,
            json={"user_id": user.telegram_user_id, "wallet_address": user.wallet.address},
        )
        return self._required(payload, "play_code", "code")

    async def start_session(self, user: UserState, play_code: str) -> str:
        payload = await self._request(
            "POST",
            self.session_path,
            json={"user_id": user.telegram_user_id, "play_code": play_code, "wallet_address": user.wallet.address},
        )
        return self._required(payload, "session_id", "id")

    async def read_state(self, user: UserState) -> GameState:
        if not user.session_id:
            raise RuntimeError("external session is not ready; run /start first")
        payload = await self._request("GET", self.state_path, params={"session_id": user.session_id})
        return self._state(payload)

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        if not user.session_id:
            raise RuntimeError("external session is not ready; run /start first")
        payload = await self._request("POST", self.action_path, json={"session_id": user.session_id, "action": action})
        return self._state(payload)

    async def upgrade(self, user: UserState) -> GameState:
        return await self.submit_action(user, "upgrade")


@dataclass
class _DemoSession:
    state: GameState
    rng: random.Random
    asteroids_remaining: int = 12
    turns: int = 0


class DemoGameAdapter(GameAdapter):
    """Offline game loop for demos and judging; it never contacts a website."""

    def __init__(self) -> None:
        self.sessions: dict[str, _DemoSession] = {}

    async def request_play_code(self, user: UserState) -> str:
        digest = hashlib.sha256(str(user.telegram_user_id).encode()).hexdigest()[:6].upper()
        return f"DEMO-{digest}"

    async def start_session(self, user: UserState, play_code: str) -> str:
        session_id = f"demo-{user.telegram_user_id}"
        seed = user.telegram_user_id ^ int(hashlib.sha256(play_code.encode()).hexdigest()[:8], 16)
        state = GameState(
            resources={"ore": 0, "metal": 0, "fuel": 100, "upgrade_tokens": 0},
            position={"x": 0.0, "y": 0.0},
            ship="SCRAP-01",
            rank=1,
            upgrades={"mining": 1, "hull": 1},
        )
        self.sessions[session_id] = _DemoSession(state=state, rng=random.Random(seed))
        return session_id

    def _session(self, user: UserState) -> _DemoSession:
        if not user.session_id or user.session_id not in self.sessions:
            raise RuntimeError("Demo session is not ready; run /start first")
        return self.sessions[user.session_id]

    async def read_state(self, user: UserState) -> GameState:
        session = self._session(user)
        session.state.cooldown_seconds = max(0.0, session.state.cooldown_seconds - 0.5)
        return session.state

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        session = self._session(user)
        state = session.state
        session.turns += 1
        state.raw = {"last_action": action, "asteroids_remaining": session.asteroids_remaining}
        if action == "wait":
            state.cooldown_seconds = 0.0
        elif action == "fire" and state.cooldown_seconds <= 0:
            if session.asteroids_remaining > 0:
                mined = session.rng.randint(9, 18) + state.upgrades.get("mining", 1) * 2
                session.asteroids_remaining -= 1
                state.resources["ore"] += mined
                state.resources["metal"] += mined // 2
                state.score += mined * 10
                state.resources["upgrade_tokens"] += 1 if session.asteroids_remaining % 4 == 0 else 0
                state.cooldown_seconds = 1.0
            else:
                state.game_over = True
        elif action == "thrust" and state.resources.get("fuel", 0) >= 5:
            state.resources["fuel"] -= 5
            state.position["x"] += session.rng.uniform(-4, 4)
            state.position["y"] += session.rng.uniform(-4, 4)
            state.score += 5
        elif action == "rotate_left":
            state.position["x"] -= 1
        elif action == "rotate_right":
            state.position["x"] += 1
        return state

    async def upgrade(self, user: UserState) -> GameState:
        session = self._session(user)
        state = session.state
        metal = state.resources.get("metal", 0)
        tokens = state.resources.get("upgrade_tokens", 0)
        if metal < 100 and tokens <= 0:
            return state
        if metal >= 100:
            state.resources["metal"] -= 100
        else:
            state.resources["upgrade_tokens"] -= 1
        state.upgrades["mining"] = state.upgrades.get("mining", 1) + 1
        state.upgrades["hull"] = state.upgrades.get("hull", 1) + 1
        state.ship = f"FORGE-{state.upgrades['mining']:02d}"
        state.score += 100
        state.raw = {"last_action": "upgrade", "asteroids_remaining": session.asteroids_remaining}
        return state


class SelectableGameAdapter(GameAdapter):
    """Select demo or an external adapter from each user's persisted target."""

    def __init__(self, default_target: str, **external_options: str) -> None:
        self.default_target = normalize_target(default_target)
        self.demo = DemoGameAdapter()
        self.external_options = external_options
        self.external: dict[str, ExternalJsonGameAdapter] = {}

    def _adapter(self, user: UserState) -> GameAdapter:
        target = normalize_target(user.target_url or self.default_target)
        if target == "demo":
            return self.demo
        if target not in self.external:
            self.external[target] = ExternalJsonGameAdapter(target, **self.external_options)
        return self.external[target]

    async def request_play_code(self, user: UserState) -> str:
        return await self._adapter(user).request_play_code(user)

    async def start_session(self, user: UserState, play_code: str) -> str:
        return await self._adapter(user).start_session(user, play_code)

    async def read_state(self, user: UserState) -> GameState:
        return await self._adapter(user).read_state(user)

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        return await self._adapter(user).submit_action(user, action)

    async def upgrade(self, user: UserState) -> GameState:
        return await self._adapter(user).upgrade(user)
