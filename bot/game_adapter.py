from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import random
import time
import uuid
from urllib.parse import urlparse

import httpx

from .models import ActionName, GameState, UserState
from .wallet import SolanaSigner


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
    target = value.strip()
    if target.lower() in {"demo", "local", "offline"}:
        return "demo"
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("target must be 'demo' or an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("target URLs must not contain credentials")
    return target.rstrip("/")


class PlanetForgeAdapter(GameAdapter):
    """Client for Planet Forge's authenticated Base44 function contract."""

    def __init__(self, base_url: str, signer: SolanaSigner, app_id: str = "6a845b273cbe45715e037048", timeout_seconds: float = 15.0) -> None:
        self.base_url = normalize_target(base_url)
        if self.base_url == "demo":
            raise ValueError("Planet Forge adapter requires an http(s) URL")
        self.signer = signer
        self.app_id = app_id
        self.timeout_seconds = timeout_seconds
        self.token: str | None = None
        self.anonymous_id = str(uuid.uuid4())
        self._runs: dict[int, dict] = {}

    def _url(self, function: str) -> str:
        return f"{self.base_url}/api/apps/{self.app_id}/functions/{function}"

    async def _request(self, function: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.post(
                    self._url(function),
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json", "X-Origin-URL": self.base_url + "/", "X-Base44-Anonymous-Id": self.anonymous_id},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Planet Forge {function} returned HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"could not reach external target {self.base_url}: {exc}") from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Planet Forge {function} returned non-JSON content ({response.headers.get('content-type', 'unknown')})") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"Planet Forge {function} must return a JSON object")
        if result.get("error"):
            error = result["error"]
            raise RuntimeError(error.get("message", str(error)) if isinstance(error, dict) else str(error))
        return result

    async def _ensure_auth(self, user: UserState) -> None:
        if self.token:
            return
        nonce = await self._request("authNonce", {"walletAddress": user.wallet.address})
        session_id, message = nonce.get("sessionId"), nonce.get("message")
        if not session_id or not message:
            raise RuntimeError("Planet Forge authNonce did not return sessionId and message")
        verified = await self._request(
            "authVerify",
            {"sessionId": session_id, "walletAddress": user.wallet.address, "signature": list(self.signer.sign(str(message))), "referralCode": None},
        )
        self.token = str(verified.get("token") or "")
        if not self.token:
            raise RuntimeError("Planet Forge authVerify did not return a token")

    async def _invoke(self, function: str, user: UserState, **args: object) -> dict:
        await self._ensure_auth(user)
        return await self._request(function, {"token": self.token, **args})

    @staticmethod
    def _state(payload: dict) -> GameState:
        data = payload.get("state", payload)
        if not isinstance(data, dict):
            raise RuntimeError("Planet Forge state response must contain a JSON object")
        player = data.get("player", {}) if isinstance(data.get("player", {}), dict) else {}
        resources = data.get("resources", data.get("materials", {}))
        if not isinstance(resources, dict):
            resources = {}
        excluded = {"player", "inventory", "score", "resources", "materials", "position", "ship", "rank", "upgrades", "cooldown_seconds", "dead", "game_over"}
        return GameState(
            score=int(data.get("score", player.get("xp", 0))),
            resources=dict(resources),
            position=dict(data.get("position", {})) if isinstance(data.get("position", {}), dict) else {},
            ship=str(data.get("ship", player.get("equippedShipId", "unknown"))),
            rank=int(data.get("rank", player.get("level", 0))),
            upgrades=dict(data.get("upgrades", {})) if isinstance(data.get("upgrades", {}), dict) else {},
            cooldown_seconds=float(data.get("cooldown_seconds", 0.0)),
            alive=not bool(data.get("dead", False)),
            game_over=bool(data.get("game_over", False)),
            raw={"player": player, "inventory": data.get("inventory", []), **{key: value for key, value in data.items() if key not in excluded}},
        )

    async def request_play_code(self, user: UserState) -> str:
        await self._ensure_auth(user)
        return f"PLANET-FORGE-{user.wallet.address[:8]}"

    async def start_session(self, user: UserState, play_code: str) -> str:
        state = await self._invoke("playerState", user)
        catalog = await self._invoke("catalog", user)
        levels = catalog.get("levels", [])
        if not levels:
            raise RuntimeError("Planet Forge catalog has no playable levels")
        level = next((item for item in levels if isinstance(item, dict) and not item.get("locked")), levels[0])
        inventory = state.get("inventory", [])
        ships = [item for item in inventory if isinstance(item, dict) and item.get("itemKind") == "ship"]
        player = state.get("player", {}) if isinstance(state.get("player", {}), dict) else {}
        ship = next((item for item in ships if item.get("id") == player.get("equippedShipId")), None) or (ships[0] if ships else None)
        if not ship:
            raise RuntimeError("Planet Forge player has no ship inventory item")
        run = await self._invoke("startRun", user, levelId=level.get("id"), shipInvId=ship.get("id"), defendMissionId="")
        run_id = str(run.get("runId") or "")
        if not run_id:
            raise RuntimeError("Planet Forge startRun did not return runId")
        self._runs[user.telegram_user_id] = {"run_id": run_id, "heartbeat_token": run.get("heartbeatToken"), "level_id": level.get("id"), "ship_inv_id": ship.get("id"), "started_at": time.monotonic(), "duration": float(level.get("durationSec", 90)), "kills": 0, "inputs": 0, "completed": False}
        return run_id

    async def read_state(self, user: UserState) -> GameState:
        payload = await self._invoke("playerState", user)
        run = self._runs.get(user.telegram_user_id)
        if run and not run["completed"] and time.monotonic() - run["started_at"] >= run["duration"]:
            await self._complete(user, run, survived=True)
            payload["game_over"] = True
        return self._state(payload)

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        run = self._runs.get(user.telegram_user_id)
        if not run:
            raise RuntimeError("Planet Forge run is not ready; run /start first")
        if action != "wait":
            run["inputs"] += 1
        if action == "fire":
            run["kills"] += 1
        await self._invoke("runHeartbeat", user, runId=run["run_id"], heartbeatToken=run["heartbeat_token"], kills=run["kills"], inputs=run["inputs"])
        return await self.read_state(user)

    async def _complete(self, user: UserState, run: dict, survived: bool) -> dict:
        if run["completed"]:
            return {}
        result = {"timeMs": int((time.monotonic() - run["started_at"]) * 1000), "kills": run["kills"], "materials": {}, "survived": survived}
        payload = await self._invoke("completeLevel", user, levelId=run["level_id"], shipInvId=run["ship_inv_id"], runId=run["run_id"], result=result)
        run["completed"] = True
        return payload

    async def upgrade(self, user: UserState) -> GameState:
        return await self.read_state(user)

    async def equip_item(self, user: UserState, **args: object) -> dict:
        return await self._invoke("equipItem", user, **args)

    async def craft_item(self, user: UserState, **args: object) -> dict:
        return await self._invoke("craftItem", user, **args)


ExternalJsonGameAdapter = PlanetForgeAdapter


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
        state = GameState(resources={"ore": 0, "metal": 0, "fuel": 100, "upgrade_tokens": 0}, position={"x": 0.0, "y": 0.0}, ship="SCRAP-01", rank=1, upgrades={"mining": 1, "hull": 1})
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
    """Select demo or Planet Forge from each user's persisted target."""

    def __init__(self, default_target: str, signer: SolanaSigner | None = None, **external_options: str) -> None:
        self.default_target = normalize_target(default_target)
        self.demo = DemoGameAdapter()
        self.signer = signer
        self.external_options = external_options
        self.external: dict[str, PlanetForgeAdapter] = {}

    def _adapter(self, user: UserState) -> GameAdapter:
        target = normalize_target(user.target_url or self.default_target)
        if target == "demo":
            return self.demo
        if self.signer is None:
            raise RuntimeError("Planet Forge mode requires SOLANA_PRIVATE_KEY")
        if target not in self.external:
            self.external[target] = PlanetForgeAdapter(target, signer=self.signer, **self.external_options)
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
