# Asteroid Telegram Bot

Telegram-controlled asteroid-mining game runner for the hackathon. In the default **Demo Forge** mode, each player gets a deterministic play code and an offline session where the bot starts a scrap ship, shatters asteroids, harvests ore and metal, and forges upgrades.

## Safety and scope

Use this repository only with the built-in demo or an isolated, authorized test harness that you control. Do not point it at a real game, exchange, wallet, or account. Never commit `.env`, generated state, session cookies, private keys, or Telegram tokens. The generated wallet record is a local demo placeholder, not a Solana wallet and not suitable for real funds.

The bot can connect to a website only when that website exposes the documented JSON test-harness contract below. It cannot automate an arbitrary HTML page, wallet extension, CAPTCHA, or undocumented frontend API.

## Commands

- `/start` — initialize the current target and display the play code.
- `/target demo` — select the offline demo.
- `/target https://your-authorized-test-harness.example` — select an external target for this user and clear the old session.
- `/play` — start the per-user mining loop.
- `/stop` — stop the loop gracefully.
- `/status` — show the current target and latest game state.

Each user has an independent persisted target. Selecting a target stops the current loop and requires `/start` before `/play`.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
# set TELEGRAM_BOT_TOKEN
python -m bot
```

## Targets and JSON contract

The default is `GAME_MODE=demo`. To configure the default external target instead, set `GAME_MODE=external` and `GAME_BASE_URL` in `.env`. A user can override that default at any time with `/target <absolute-http(s)-url>`.

The external target is expected to expose these endpoints relative to the selected base URL:

| Method | Default path | Request | Required response |
|---|---|---|---|
| POST | `/api/play-code` | `{ "user_id": 123, "wallet_address": "..." }` | `{ "play_code": "..." }` |
| POST | `/api/session` | `{ "user_id": 123, "play_code": "...", "wallet_address": "..." }` | `{ "session_id": "..." }` |
| GET | `/api/state` | query `session_id=...` | game-state object or `{ "state": { ... } }` |
| POST | `/api/action` | `{ "session_id": "...", "action": "fire" }` | game-state object or `{ "state": { ... } }` |

A game-state object may contain `score`, `resources`, `position`, `ship`, `rank`, `upgrades`, `cooldown_seconds`, `alive`, and `game_over`. Unknown fields are preserved in `raw`. The upgrade action is sent as `action: "upgrade"`.

Override paths with `GAME_PLAY_CODE_ENDPOINT`, `GAME_SESSION_ENDPOINT`, `GAME_STATE_ENDPOINT`, and `GAME_ACTION_ENDPOINT`. The adapter follows redirects, requires JSON responses, reports HTTP errors clearly, and never treats an HTML page as a successful API response.

## `/site` wallet companion

The `site/` directory is a static, browser-only companion for a manual PlanetForge flow. Serve it locally with `python3 -m http.server 8000 --directory site`, then open `http://localhost:8000`. The page can generate a Solana keypair locally and connect installed wallet providers, but it does not send keys to this bot or automate a website.

## Tests

```bash
python -m pytest -q
python -m compileall -q bot scripts tests
node --check site/app.js
```

The test suite covers target validation, the controller policy, and the demo adapter. GitHub Actions runs the same tests and static checks.
