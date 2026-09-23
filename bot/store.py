from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import GameState, UserState, Wallet


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.users: dict[int, UserState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        for raw in data.get("users", []):
            game = GameState(**raw.get("last_game", {}))
            wallet = Wallet(**raw["wallet"])
            self.users[int(raw["telegram_user_id"])] = UserState(
                telegram_user_id=int(raw["telegram_user_id"]),
                wallet=wallet,
                play_code=raw.get("play_code"),
                session_id=raw.get("session_id"),
                running=False,
                last_game=game,
            )

    def save(self) -> None:
        payload: dict[str, Any] = {"users": [asdict(user) for user in self.users.values()]}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2))
        temporary.replace(self.path)

    def get(self, telegram_user_id: int) -> UserState | None:
        return self.users.get(telegram_user_id)

    def put(self, user: UserState) -> None:
        self.users[user.telegram_user_id] = user
        self.save()
