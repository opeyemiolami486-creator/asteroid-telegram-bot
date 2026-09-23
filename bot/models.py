from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ActionName = Literal["rotate_left", "rotate_right", "thrust", "fire", "wait", "upgrade"]


@dataclass
class Wallet:
    address: str
    private_key: str


@dataclass
class GameState:
    score: int = 0
    resources: dict[str, int] = field(default_factory=dict)
    position: dict[str, float] = field(default_factory=dict)
    ship: str = "unknown"
    rank: int = 0
    upgrades: dict[str, int] = field(default_factory=dict)
    cooldown_seconds: float = 0.0
    alive: bool = True
    game_over: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserState:
    telegram_user_id: int
    wallet: Wallet
    play_code: str | None = None
    session_id: str | None = None
    running: bool = False
    last_game: GameState = field(default_factory=GameState)

    def public_summary(self) -> dict[str, Any]:
        payload = asdict(self.last_game)
        payload.pop("raw", None)
        return payload
