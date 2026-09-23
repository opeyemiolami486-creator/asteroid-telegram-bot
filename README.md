# Asteroid Telegram Bot

Telegram-controlled Planet Forge pilot for the hackathon. The bot supports the offline **Demo Forge** mode and the fake reference site at `https://planet-forge.com`.

## Safety and scope

Use the demo or the hackathon reference site only. Never commit `.env`, generated state, session cookies, private keys, or Telegram tokens. External mode uses a real Solana Ed25519 key supplied through `SOLANA_PRIVATE_KEY`; the private key stays local, while the bot sends only the public address and the 64-byte signature over Planet Forge's one-time nonce.

## Commands

- `/start` — authenticate the configured pilot and initialize the current target.
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

## Targets

Set `GAME_MODE=external`, `GAME_BASE_URL=https://planet-forge.com`, and `SOLANA_PRIVATE_KEY` in `.env`. The adapter mirrors the reference browser client: `authNonce` → local Ed25519 signature → `authVerify`, then authenticated `playerState`, `catalog`, `startRun`, `runHeartbeat`, and `completeLevel` function calls at `/api/apps/6a845b273cbe45715e037048/functions/<name>`. Optional `equipItem` and `craftItem` helpers use the same authenticated function client. There are deliberately no `/api/play-code`, `/api/session`, `/api/state`, or `/api/action` calls.

The bot chooses the first unlocked catalog level and the player's equipped/first ship, sends heartbeat input counts while its conservative rotate-and-shoot policy runs, and submits the mission result after the level duration. A user can override the target with `/target <absolute-http(s)-url>` when testing an equivalent isolated reference harness.

## `/site` wallet companion

Use Phantom, Solflare, or Backpack to create/hold the pilot wallet, export its secret key in the wallet's supported JSON/base58 format, and set it locally as `SOLANA_PRIVATE_KEY`. Do not paste it into Telegram or commit it. The bot performs the same nonce-signing operation as the browser flow without attempting to automate a browser extension.

## Tests

```bash
python -m pytest -q
python -m compileall -q bot scripts tests
node --check site/app.js
```

The test suite covers target validation, the controller policy, and the demo adapter. GitHub Actions runs the same tests and static checks.
