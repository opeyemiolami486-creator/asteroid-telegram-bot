# Asteroid Telegram Bot

Public hackathon scaffold for a Telegram-controlled asteroid game runner. The bot creates a per-user local wallet record, requests a unique play code through a game adapter, and reports run statistics after each play. The adapter is intentionally unimplemented until an isolated, authorized test harness and its request/response flow are supplied.

## Safety and scope

This repository must only be used against an isolated, authorized hackathon test harness. Do not point it at `planet-forge.com` or any real game, exchange, wallet, or account: its public tutorial describes real Solana wallet signing, SOL forge fees, server-side reward controls, and detection or suspension of scripted play. Never commit `.env`, generated state, session cookies, private keys, or Telegram tokens. The generated wallet secret is stored locally only and is shown once in `/start`; replace the local wallet provider with the test harness's documented wallet format before using it for login.

## Commands

- `/start` — create or display the user's bot profile and wallet details, then request a play code.
- `/play` — start the per-user loop.
- `/stop` — stop the loop gracefully.
- `/status` — show the most recent score, resources, position, ship, rank, upgrades, and cooldown.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set TELEGRAM_BOT_TOKEN and the fake game URL/paths
python -m bot
```

## Adapter contract

`bot/game_adapter.py` defines the integration boundary:

1. request a unique play code for a Telegram user and wallet address;
2. exchange the play code for a game session;
3. read the current game state;
4. submit one legal action;
5. perform an upgrade when resources and cooldown permit.

The controller uses an explicit state/action model and will not infer undocumented endpoints. Once an isolated test URL or local API fixture is provided, capture that fake API or browser flow, implement the adapter, add fixture tests, and run an authorized end-to-end smoke test. The current public PlanetForge URL is documentation only and is not an implementation target.
