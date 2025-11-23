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

	### Troubleshooting: Render detected Elixir/other language
	- If your initial Render deploy tries to use Elixir/OTP (e.g., `mix phx.digest` or "Using Erlang version"), it means the service is configured with the wrong environment.
	- To fix this, either:
		- In Render Dashboard, edit the service and change **Environment** to **Python** and update the **Build & Start Commands** accordingly, or
		- Re-create a new **Web Service** and choose **Python** as the runtime and use the `startCommand` `python bot.py` (or `Procfile`) and `buildCommand` `pip install -r requirements.txt`.
		- Ensure the **Root Directory** is set to your repo root (or `/`) so Render detects the repository's `runtime.txt`, `requirements.txt`, `Procfile`, and `render.yaml`.

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

