from __future__ import annotations

import logging

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .controller import GameController
from .game_adapter import ReferenceSiteAdapter
from .models import UserState
from .store import StateStore
from .wallet import LocalWalletProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class Settings(BaseSettings):
    telegram_bot_token: str
    state_file: str = "./data/state.json"
    poll_seconds: float = 2.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def build_app() -> Application:
    load_dotenv()
    settings = Settings()
    store = StateStore(settings.state_file)
    wallet_provider = LocalWalletProvider()
    adapter = ReferenceSiteAdapter()
    app = Application.builder().token(settings.telegram_bot_token).build()

    async def notify(user_id: int, text: str) -> None:
        await app.bot.send_message(chat_id=user_id, text=text)

    controller = GameController(store, adapter, notify, settings.poll_seconds)

    def get_user(update: Update) -> UserState:
        assert update.effective_user is not None
        user = store.get(update.effective_user.id)
        if user is None:
            user = UserState(update.effective_user.id, wallet_provider.create())
            store.put(user)
        return user

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        wallet = user.wallet
        try:
            if not user.play_code:
                play_code = await controller.prepare(user)
            else:
                play_code = user.play_code
            await update.message.reply_text(
                "Profile ready.\n"
                f"Wallet address: {wallet.address}\n"
                f"Wallet secret (show once; keep private): {wallet.private_key}\n"
                f"Unique play code: {play_code}\n\n"
                "Use /play to begin, /status for stats, or /stop to halt."
            )
        except Exception as exc:
            await update.message.reply_text(f"Profile created, but the fake game adapter is not configured yet: {exc}")

    async def play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        try:
            await controller.start(user)
            await update.message.reply_text("Play loop started. Use /stop to halt it.")
        except Exception as exc:
            await update.message.reply_text(f"Cannot start yet: {exc}")

    async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        await controller.stop(user)
        await update.message.reply_text("Play loop stopped safely.")

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        s = user.last_game
        await update.message.reply_text(
            f"running={user.running}\nscore={s.score}\nresources={s.resources}\nposition={s.position}\n"
            f"ship={s.ship}\nrank={s.rank}\nupgrades={s.upgrades}\ncooldown={s.cooldown_seconds:.1f}s"
        )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))
    return app


def main() -> None:
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
