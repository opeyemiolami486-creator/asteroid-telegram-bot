import asyncio

from bot.game_adapter import DemoGameAdapter
from bot.models import UserState, Wallet


async def main() -> None:
    adapter = DemoGameAdapter()
    user = UserState(42, Wallet("demo", "not-a-real-key"))
    user.play_code = await adapter.request_play_code(user)
    user.session_id = await adapter.start_session(user, user.play_code)
    for _ in range(3):
        await adapter.submit_action(user, "fire")
        await adapter.read_state(user)
    state = await adapter.upgrade(user)
    print(user.play_code, state.score, state.resources, state.ship)


if __name__ == "__main__":
    asyncio.run(main())
