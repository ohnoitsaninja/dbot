# dbot

This repository contains a Discord bot that uses `discord.py`, and a small aiohttp webserver that exposes a health and status endpoint.

## Deploying to Render.com (Web Service)

1. On Render, create a new **Web Service** and connect this GitHub repo.
2. Select **Runtime**: `Python`.
3. Build Command: you can leave empty or use `pip install -r requirements.txt`.
4. Start Command: `python bot.py` (the `Procfile` already contains this).
5. Set environment variables in the Render UI:
	- `DISCORD_TOKEN`: your bot token
	- `GROK_API_KEY`: your Grok API key (if used)
6. Set the **Health Check Path** to `/health`.

Note: If you'd prefer to run the bot as a background worker, create a Background Worker in Render instead and use the same start command.

## Local development & testing

1. Create a virtual environment and activate it:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and add your tokens.

```bash
cp .env.example .env
# edit .env to add keys
```

4. Run the app locally:

```bash
python bot.py
```

5. Open http://localhost:8080/health to confirm the service is up (you should see `OK`).

