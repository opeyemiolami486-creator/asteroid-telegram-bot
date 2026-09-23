from __future__ import annotations

import logging

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .controller import GameController
from .game_adapter import SelectableGameAdapter, normalize_target
from .models import GameState, UserState
from .store import StateStore
from .wallet import DemoWalletProvider, SolanaWalletProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class Settings(BaseSettings):
    telegram_bot_token: str
    game_mode: str = "demo"
    game_base_url: str = "https://play.stonkscape.com/rs2.cgi"
    stonkscape_bridge_url: str = ""
    solana_private_key: str = ""
    planet_forge_app_id: str = ""
    state_file: str = "./data/state.json"
    poll_seconds: float = 2.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def build_app() -> Application:
    load_dotenv()
    settings = Settings()
    store = StateStore(settings.state_file)
    if settings.game_mode.lower() == "demo":
        default_target = "demo"
        wallet_provider = DemoWalletProvider()
        signer = None
    elif settings.game_mode.lower() == "stonkscape":
        default_target = settings.game_base_url
        wallet_provider = DemoWalletProvider()
        signer = None
    elif settings.game_base_url:
        default_target = settings.game_base_url
        wallet_provider = SolanaWalletProvider(settings.solana_private_key)
        signer = wallet_provider.signer
    else:
        raise ValueError("GAME_BASE_URL is required when GAME_MODE is not demo")
    adapter = SelectableGameAdapter(
        default_target,
        signer=signer,
        game_mode=settings.game_mode,
        bridge_url=settings.stonkscape_bridge_url,
        app_id=settings.planet_forge_app_id,
    )
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
        elif signer is not None and user.wallet.address != signer.address:
            user.wallet = wallet_provider.create()
            user.play_code = None
            user.session_id = None
            store.put(user)
        return user

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        try:
            if not user.play_code:
                play_code = await controller.prepare(user)
            else:
                play_code = user.play_code
            await update.message.reply_text(
                "Profile ready.\n"
                f"Target: {user.target_url or default_target}\n"
                f"Unique play code: {play_code}\n\n"
                "Use /play to begin, /status for stats, /target <demo|https://your-test-harness> to switch target, or /stop to halt."
            )
        except Exception as exc:
            await update.message.reply_text(f"Could not initialize target {user.target_url or default_target}: {exc}")

    async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        if settings.game_mode.lower() != "stonkscape":
            await update.message.reply_text("The offline demo does not need a game login.")
            return
        if len(context.args) != 2:
            await update.message.reply_text(
                "StonkScape uses its Existing User login.\n"
                "Send /login <game_username> <game_password> in a private chat.\n"
                "The bot will not echo or persist your password."
            )
            return
        username, password = context.args
        try:
            await update.message.delete()
        except Exception:
            # Deletion depends on Telegram chat permissions; the private-chat
            # warning remains the primary protection against credential exposure.
            pass
        try:
            await adapter.login(user, username, password)
            user.play_code = None
            user.session_id = None
            store.put(user)
            await update.message.reply_text(
                f"Logged in to StonkScape as {user.game_username}.\n"
                "Run /start to request a unique play code, then /play."
            )
        except Exception as exc:
            await update.message.reply_text(f"StonkScape login failed: {exc}")

    async def target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        value = " ".join(context.args).strip()
        if not value:
            await update.message.reply_text(
                "Usage: /target demo\n"
                "or: /target https://your-authorized-test-harness.example\n\n"
                "The target must be an authorized JSON integration configured for this bot."
            )
            return
        try:
            selected = normalize_target(value)
            await controller.stop(user)
            user.target_url = selected
            user.play_code = None
            user.session_id = None
            user.last_game = GameState()
            store.put(user)
            await update.message.reply_text(
                f"Target selected: {selected}\n"
                "Session cleared. Run /start to initialize this target, then /play."
            )
        except Exception as exc:
            await update.message.reply_text(f"Target not changed: {exc}")

    async def play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = get_user(update)
        try:
            await controller.start(user)
            await update.message.reply_text(f"Play loop started against {user.target_url or default_target}. Use /stop to halt it.")
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
            f"target={user.target_url or default_target}\n"
            f"running={user.running}\nscore={s.score}\nresources={s.resources}\nposition={s.position}\n"
            f"ship={s.ship}\nrank={s.rank}\nupgrades={s.upgrades}\ncooldown={s.cooldown_seconds:.1f}s"
        )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("target", target))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))
    return app


def main() -> None:
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
