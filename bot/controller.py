from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .game_adapter import GameAdapter
from .models import UserState
from .store import StateStore

Notify = Callable[[int, str], Awaitable[None]]


class GameController:
    def __init__(self, store: StateStore, adapter: GameAdapter, notify: Notify, poll_seconds: float) -> None:
        self.store = store
        self.adapter = adapter
        self.notify = notify
        self.poll_seconds = poll_seconds
        self.tasks: dict[int, asyncio.Task[None]] = {}

    async def prepare(self, user: UserState) -> str:
        user.play_code = await self.adapter.request_play_code(user)
        user.session_id = await self.adapter.start_session(user, user.play_code)
        self.store.put(user)
        return user.play_code

    async def start(self, user: UserState) -> None:
        if user.running:
            return
        if not user.session_id:
            await self.prepare(user)
        user.running = True
        self.store.put(user)
        self.tasks[user.telegram_user_id] = asyncio.create_task(self._run(user))

    async def stop(self, user: UserState) -> None:
        user.running = False
        task = self.tasks.pop(user.telegram_user_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.store.put(user)

    async def _run(self, user: UserState) -> None:
        try:
            while user.running:
                state = await self.adapter.read_state(user)
                user.last_game = state
                self.store.put(user)
                if state.game_over or not state.alive:
                    await self.notify(user.telegram_user_id, self._summary(user, "run ended"))
                    user.running = False
                    break
                if self._upgrade_available(state):
                    state = await self.adapter.upgrade(user)
                else:
                    state = await self.adapter.submit_action(user, self._choose_action(state))
                user.last_game = state
                self.store.put(user)
                await self.notify(user.telegram_user_id, self._summary(user, "tick"))
                await asyncio.sleep(max(self.poll_seconds, state.cooldown_seconds))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            user.running = False
            self.store.put(user)
            await self.notify(user.telegram_user_id, f"Run paused safely: {exc}")

    @staticmethod
    def _upgrade_available(state) -> bool:
        return bool(state.resources.get("upgrade_tokens", 0) > 0 or state.resources.get("metal", 0) >= 100)

    @staticmethod
    def _choose_action(state):
        # Conservative placeholder policy; replace with a policy driven by the reference site's state schema.
        if state.cooldown_seconds > 0:
            return "wait"
        return "fire"

    @staticmethod
    def _summary(user: UserState, label: str) -> str:
        s = user.last_game
        return (
            f"{label}: score={s.score}, resources={s.resources}, position={s.position}, "
            f"ship={s.ship}, rank={s.rank}, upgrades={s.upgrades}, cooldown={s.cooldown_seconds:.1f}s"
        )
