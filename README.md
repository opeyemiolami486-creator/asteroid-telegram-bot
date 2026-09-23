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
# set TELEGRAM_BOT_TOKEN and the game variables below
python -m bot
```

## Railway deployment

Railway can deploy this repository directly. Current Railway Railpack uses `requirements.txt` and `railpack.json`, with the `Procfile` as a fallback; the service is a long-running Telegram polling worker, not an HTTP web service. The configured start command is `python -m bot`, and the added `bot/__main__.py` makes that module invocation valid.

Create a Railway service from the GitHub repository, add the variables below, and deploy from `main`. Do not set a port or run `uvicorn`; Telegram polling does not require an inbound HTTP port.

For persistent user sessions, attach a Railway Volume mounted at `/app/data` and set `STATE_FILE=/app/data/state.json`. Without a volume, the bot still runs but its local user/session state can be lost whenever Railway replaces the container.

Required variables for the real reference site:

```text
TELEGRAM_BOT_TOKEN=<Telegram BotFather token>
GAME_MODE=external
GAME_BASE_URL=https://planet-forge.com
SOLANA_PRIVATE_KEY=<base58, hex, or JSON-array Solana secret key; store as a Railway secret>
PLANET_FORGE_APP_ID=6a845b273cbe45715e037048
STATE_FILE=/app/data/state.json
POLL_SECONDS=2
```

For an offline deployment, use `GAME_MODE=demo` and omit `SOLANA_PRIVATE_KEY`; the other variables can remain configured. Never commit or print the private key.

## Targets

Set `GAME_MODE=external`, `GAME_BASE_URL=https://planet-forge.com`, and `SOLANA_PRIVATE_KEY` in `.env`. The adapter mirrors the reference browser client: `authNonce` → local Ed25519 signature → `authVerify`, then authenticated `playerState`, `catalog`, `startRun`, `runHeartbeat`, and `completeLevel` function calls at `/api/apps/6a845b273cbe45715e037048/functions/<name>`. Optional `equipItem` and `craftItem` helpers use the same authenticated function client. There are deliberately no `/api/play-code`, `/api/session`, `/api/state`, or `/api/action` calls.

The bot selects the highest normal sector unlocked by XP, sends browser-compatible 30-second heartbeat input counts while its rotate-and-shoot policy runs, confirms the mission result, and automatically enters the next sector. It keeps doing this until `/stop`. Every 30 seconds it also evaluates materials and ship progression. When a craft is affordable it obtains a quote; when a better ship is not craftable it reports a buy recommendation. It does **not** silently submit a Solana payment transaction from the pilot wallet.

## `/site` wallet companion

Use Phantom, Solflare, or Backpack to create/hold the pilot wallet, export its secret key in the wallet's supported JSON/base58 format, and set it locally as `SOLANA_PRIVATE_KEY`. Do not paste it into Telegram or commit it. The bot performs the same nonce-signing operation as the browser flow without attempting to automate a browser extension.

## Tests

```bash
python -m pytest -q
python -m compileall -q bot scripts tests
node --check site/app.js
```

The test suite covers target validation, the controller policy, the Planet Forge adapter, and the demo adapter. GitHub Actions and the Railway-equivalent local checks run the same tests and static checks.
