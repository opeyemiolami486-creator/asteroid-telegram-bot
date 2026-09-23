from __future__ import annotations

from abc import ABC, abstractmethod

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
    """Implement only after the supplied fake reference site's contract is inspected."""

    async def request_play_code(self, user: UserState) -> str:
        raise RuntimeError("Reference site not configured: provide the fake site URL and play-code flow")

    async def start_session(self, user: UserState, play_code: str) -> str:
        raise RuntimeError("Reference site session flow is not configured")

    async def read_state(self, user: UserState) -> GameState:
        raise RuntimeError("Reference site state-reading flow is not configured")

    async def submit_action(self, user: UserState, action: ActionName) -> GameState:
        raise RuntimeError("Reference site action flow is not configured")

    async def upgrade(self, user: UserState) -> GameState:
        raise RuntimeError("Reference site upgrade flow is not configured")
