from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from .game_adapter import GameAdapter, PlanetForgeShipRepairError
from .models import GameState, UserState
from .store import StateStore

Notify = Callable[[int, str], Awaitable[None]]


class CanvasWorker(Protocol):
    async def play(self, user: UserState, adapter: GameAdapter) -> dict[str, int]: ...
    async def close(self, user: UserState) -> None: ...


class GameController:
    def __init__(self, store: StateStore, adapter: GameAdapter, notify: Notify, poll_seconds: float, canvas_worker: CanvasWorker | None = None) -> None:
        self.store = store
        self.adapter = adapter
        self.notify = notify
        self.poll_seconds = poll_seconds
        self.canvas_worker = canvas_worker
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self.action_phase: dict[int, int] = {}
        self.high_scores: dict[int, int] = {}

    async def prepare(self, user: UserState) -> str:
        user.play_code = await self.adapter.request_play_code(user)
        user.session_id = await self.adapter.start_session(user, user.play_code)
        self.store.put(user)
        return user.play_code

    async def start(self, user: UserState) -> None:
        if user.running:
            return
        if not user.play_code:
            user.play_code = await self.adapter.request_play_code(user)
        user.running = True
        self.store.put(user)
        self.tasks[user.telegram_user_id] = asyncio.create_task(self._run(user))

    async def stop(self, user: UserState) -> None:
        user.running = False
        task = self.tasks.pop(user.telegram_user_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.canvas_worker is not None:
            await self.canvas_worker.close(user)
        self.store.put(user)

    async def _run(self, user: UserState) -> None:
        waiting_for_repairs = False
        try:
            while user.running:
                if not user.session_id:
                    try:
                        user.session_id = await self.adapter.start_session(user, user.play_code or "")
                        self.store.put(user)
                        if waiting_for_repairs:
                            await self.notify(user.telegram_user_id, "Ship repairs complete; resuming the game")
                            waiting_for_repairs = False
                    except PlanetForgeShipRepairError as exc:
                        if not waiting_for_repairs:
                            await self.notify(user.telegram_user_id, self._repair_message(exc, "waiting and will resume automatically when ready"))
                            waiting_for_repairs = True
                        reward = await self.adapter.claim_daily_reward(user)
                        if reward:
                            await self.notify(user.telegram_user_id, reward)
                        await asyncio.sleep(max(self.poll_seconds, 5.0))
                        continue
                state = await self.adapter.read_state(user)
                user.last_game = state
                self.store.put(user)
                await self.notify(user.telegram_user_id, self._summary(user, "progress"))
                await self._notify_major_events(user, state)
                if state.game_over or not state.alive:
                    summary = self._summary(user, "sector complete")
                    try:
                        next_session = await self.adapter.restart_session(user)
                    except PlanetForgeShipRepairError as exc:
                        user.session_id = None
                        if not waiting_for_repairs:
                            await self.notify(user.telegram_user_id, self._repair_message(exc, "waiting before the next sector"))
                            waiting_for_repairs = True
                        reward = await self.adapter.claim_daily_reward(user)
                        if reward:
                            await self.notify(user.telegram_user_id, reward)
                        await asyncio.sleep(max(self.poll_seconds, 5.0))
                        continue
                    if next_session:
                        user.session_id = next_session
                        user.last_game = GameState()
                        # The page that completed the previous run remains on
                        # its completion screen. Force the browser worker to
                        # create a fresh authenticated page for the new run;
                        # otherwise the controller advances server-side while
                        # the canvas keeps displaying the old level.
                        if self.canvas_worker is not None:
                            await self.canvas_worker.close(user)
                        self.store.put(user)
                        await self.notify(user.telegram_user_id, f"{summary}; entering next sector")
                        await asyncio.sleep(1)
                        continue
                    await self.notify(user.telegram_user_id, self._summary(user, "run ended"))
                    user.running = False
                    self.store.put(user)
                    break
                maintenance = await self.adapter.maintain(user)
                if maintenance:
                    await self.notify(user.telegram_user_id, f"economy: {maintenance}")
                if self.canvas_worker is not None:
                    result = await self.canvas_worker.play(user, self.adapter)
                    await self.notify(
                        user.telegram_user_id,
                        f"canvas: shots={result.get('shots_fired', 0)}, confirmed kills={result.get('targets_hit', 0)}",
                    )
                    state = await self.adapter.read_state(user)
                elif self._upgrade_available(state):
                    state = await self.adapter.upgrade(user)
                else:
                    state = await self.adapter.submit_action(user, self._next_action(user, state))
                user.last_game = state
                self.store.put(user)
                await self.notify(user.telegram_user_id, self._summary(user, "progress"))
                await self._notify_major_events(user, state)
                await self._sleep_with_countdown(user, state.cooldown_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            user.running = False
            self.store.put(user)
            await self.notify(user.telegram_user_id, f"Run paused safely: {exc}")
        finally:
            if self.canvas_worker is not None and not user.running:
                await self.canvas_worker.close(user)
            self.tasks.pop(user.telegram_user_id, None)

    @staticmethod
    def _upgrade_available(state) -> bool:
        return bool(state.resources.get("upgrade_tokens", 0) > 0 or state.resources.get("metal", 0) >= 100)

    @staticmethod
    def _repair_message(error: PlanetForgeShipRepairError, suffix: str) -> str:
        remaining = error.remaining_seconds
        if remaining is None:
            return f"Ship is in repairs; {suffix}"
        minutes, seconds = divmod(max(0, remaining), 60)
        estimate = f"approximately {minutes}m {seconds:02d}s" if minutes else f"approximately {seconds}s"
        return f"Ship is in repairs; {estimate} remaining, {suffix}"

    async def _sleep_with_countdown(self, user: UserState, cooldown_seconds: float) -> None:
        """Wait between ticks while reporting the remaining cooldown."""
        remaining = max(0.0, float(cooldown_seconds or 0.0))
        if remaining <= 0:
            await asyncio.sleep(self.poll_seconds)
            return
        deadline = time.monotonic() + remaining
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            await self.notify(user.telegram_user_id, f"cooldown: {math.ceil(remaining)}s remaining")
            await asyncio.sleep(min(max(self.poll_seconds, 0.1), remaining))

    async def _notify_major_events(self, user: UserState, state: GameState) -> None:
        previous = self.high_scores.get(user.telegram_user_id, 0)
        if state.score > previous and state.score > 0:
            self.high_scores[user.telegram_user_id] = state.score
            if previous > 0:
                await self.notify(user.telegram_user_id, f"high score: {state.score} points")

    @staticmethod
    def _choose_action(state):
        if state.cooldown_seconds > 0:
            return "wait"
        return "fire"

    @staticmethod
    def _target_bearing(state) -> float | None:
        """Return the server-reported target bearing, if one is available.

        Planet Forge preview payloads have used both a flat ``targetBearing``
        field and nested target objects.  Keeping this parser tolerant lets the
        policy aim when telemetry exists without pretending that a REST client
        can see the canvas when it does not.
        """
        raw = state.raw if isinstance(state.raw, dict) else {}
        candidates = [raw.get("targetBearing"), raw.get("target_bearing"), raw.get("bearing")]
        for key in ("target", "nearestTarget", "nearest_target", "asteroid"):
            target = raw.get(key)
            if isinstance(target, dict):
                candidates.extend((target.get("bearing"), target.get("angle"), target.get("targetBearing")))
        for value in candidates:
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _next_action(self, user: UserState, state):
        if state.cooldown_seconds > 0:
            return "wait"
        bearing = self._target_bearing(state)
        if bearing is not None:
            # Normalize degrees to the shortest signed turn.  A small deadband
            # prevents oscillating around a target and makes the next shot use
            # the server's own target alignment rather than blind rotation.
            bearing = (bearing + 180.0) % 360.0 - 180.0
            if abs(bearing) <= 8.0:
                return "fire"
            return "rotate_left" if bearing < 0 else "rotate_right"
        phase = self.action_phase.get(user.telegram_user_id, 0)
        self.action_phase[user.telegram_user_id] = phase + 1
        return ("rotate_left", "fire", "rotate_right", "fire")[phase % 4]

    @staticmethod
    def _summary(user: UserState, label: str) -> str:
        s = user.last_game
        return (
            f"{label}: score={s.score}, resources={s.resources}, position={s.position}, "
            f"ship={s.ship}, rank={s.rank}, upgrades={s.upgrades}, cooldown={s.cooldown_seconds:.1f}s"
        )
