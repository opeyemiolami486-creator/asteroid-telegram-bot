from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
import random

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


class ReferenceSiteAdapter(GameAdapter):
    """Intentionally disabled boundary for an authorized external test harness only."""

    async def request_play_code(self, user: UserState) -> str:
        raise RuntimeError("Reference site not configured: use GAME_MODE=demo or provide an authorized harness")

    async def start_session(self, user: UserState, play_code: str) -> str:
        raise RuntimeError("Reference site session flow is not configured")

    async def read_state(self, user: UserState) -> GameState:
        raise RuntimeError("Reference site state-reading flow is not configured")

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        raise RuntimeError("Reference site action flow is not configured")

    async def upgrade(self, user: UserState) -> GameState:
        raise RuntimeError("Reference site upgrade flow is not configured")


@dataclass
class _DemoSession:
    state: GameState
    rng: random.Random
    asteroids_remaining: int = 12
    turns: int = 0


class DemoGameAdapter(GameAdapter):
    """Offline game loop for demos and judging.

    The adapter models the reference site's public fantasy—spin, shatter, harvest,
    forge—but never contacts the reference website, a wallet, or a blockchain.
    """

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
        # One controller poll represents one half-second of cooldown recovery.
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
