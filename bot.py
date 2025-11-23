import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import aiohttp
from aiohttp import web
import json
from dotenv import load_dotenv
import logging
from typing import Optional

load_dotenv()

# Set up logging (visible in Render logs)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# === xAI / GROK API CONFIG ===
# Docs: https://docs.x.ai/docs/guides/chat  :contentReference[oaicite:0]{index=0}
API_URL = "https://api.x.ai/v1/chat/completions"

# NOTE: xAI docs use XAI_API_KEY; you're using GROK_API_KEY env var.
GROK_API_KEY = os.getenv("GROK_API_KEY")
if not GROK_API_KEY:
    raise ValueError("GROK_API_KEY environment variable is missing!")

headers = {
    "Authorization": f"Bearer {GROK_API_KEY}",
    "Content-Type": "application/json",
}

# Choose model via env var — defaults to Grok 4.1 Fast Reasoning
# Docs: https://docs.x.ai/docs/models  :contentReference[oaicite:1]{index=1}
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-1-fast-reasoning")
FALLBACK_MODEL = "grok-4-1-fast-non-reasoning"

VALID_MODELS = [
    "grok-4-1-fast-reasoning",
    "grok-4-1-fast-non-reasoning",
    "grok-code-fast-1",
]

if GROK_MODEL not in VALID_MODELS:
    raise ValueError(f"Invalid model '{GROK_MODEL}'. Must be one of: {', '.join(VALID_MODELS)}")


# === REAL LIVE SEARCH VIA xAI "search_parameters" (NO FAKE TOOLS) ===
# Live Search guide: https://docs.x.ai/docs/guides/live-search  :contentReference[oaicite:2]{index=2}
async def research_query(query: str, message_link: str, model: Optional[str] = None) -> str:
    logger.info(f"Starting Grok query for: {query[:50]}...")

    active_model = model or GROK_MODEL

    system_prompt = f"""You are a helpful research assistant in a Discord thread.
The user asked: "{query}"

Rules:
- Use live web search when you need real-time info (facts, news, prices, events).
- Always include clickable source links in your answer.
- Use markdown, bullet points, and code blocks when helpful.
- Keep your response under 1000 characters.
- At the end, say "Replying to: {message_link}"
- Be concise but thorough."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    # Enable xAI Live Search (real web/X/news search)
    # See "search_parameters" docs: mode / max_search_results / return_citations / sources. :contentReference[oaicite:3]{index=3}
    payload = {
        "model": active_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000,
        "search_parameters": {
            "mode": "on",              # always use live search for this bot path
            "return_citations": True,  # keep URLs + citations available
            "max_search_results": 8,   # limit cost a bit
            # "sources": [              # optional: explicit sources; defaults to web+news+X
            #     {"type": "web"},
            #     {"type": "news"},
            #     {"type": "x"},
            # ],
        },
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            logger.info(f"Sending request to Grok API with model: {active_model}")
            response = await session.post(API_URL, json=payload, headers=headers)
            logger.info(f"API Response status: {response.status}")

            data = await response.json()

            if "choices" not in data or not data["choices"]:
                error_msg = data.get("error", {}).get("message", "Unknown API error")
                logger.error(f"API Error details: {error_msg}")
                raise ValueError(f"Grok API Error: {error_msg} (Status: {response.status})")

            choice = data["choices"][0]["message"]
            content = choice.get("content", "No response content.")
            logger.info(f"Grok query successful: {len(content)} chars")
            return content

        except asyncio.TimeoutError:
            logger.error("API call timed out after 60s")
            raise ValueError("Grok API timed out (slow service—try again later)")
        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise ValueError(f"Network issue with Grok API: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in research_query: {e}")
            raise ValueError(f"Unexpected Grok error: {e}")


@bot.event
async def on_ready():
    logger.info(f"{bot.user} is online! Using model: {GROK_MODEL}")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Slash sync error: {e}")


# Simple helper to parse a Discord message URL into (guild_id, channel_id, message_id)
def parse_message_link(link: str):
    """
    Accepts URLs like:
    https://discord.com/channels/<guild_id>/<channel_id>/<message_id>
    """
    try:
        if "discord.com/channels/" not in link:
            return None
        parts = link.strip().split("discord.com/channels/")[1].split("/")
        if len(parts) < 3:
            return None
        guild_id = int(parts[0])
        channel_id = int(parts[1])
        message_id = int(parts[2])
        return guild_id, channel_id, message_id
    except Exception:
        return None


# Slash command: can accept either a message URL or free-form query text
@bot.tree.command(name="research", description="Start a research thread about a message or topic")
@app_commands.describe(message="The message URL or text you want researched")
async def research_slash(interaction: discord.Interaction, message: str):
    await interaction.response.defer()
    logger.info(f"/research triggered with: {message[:80]}...")

    # Try to treat input as a Discord message URL
    parsed = parse_message_link(message)
    if parsed:
        _, channel_id, message_id = parsed
        channel = interaction.client.get_channel(channel_id)
        if channel is None:
            await interaction.followup.send("Could not resolve that channel from the link.", ephemeral=True)
            return

        try:
            target_message = await channel.fetch_message(message_id)
        except Exception as e:
            logger.error(f"Failed to fetch message from link: {e}")
            await interaction.followup.send("Could not fetch that message from the link.", ephemeral=True)
            return

        # Reuse the same thread-based flow as the 🤖 reaction
        await do_research(target_message)
        await interaction.followup.send("Started research thread for that message.", ephemeral=True)
        return

    # Otherwise treat the input as a plain research question in the current channel
    try:
        original_link = interaction.channel.jump_url if interaction.channel else "Direct /research invocation"
        answer = await research_query(message, original_link)

        # Truncate to avoid Discord 2000 char limit
        max_content_length = 1800
        if len(answer) > max_content_length:
            answer = answer[:max_content_length] + "\n... (truncated)"

        footer = f"\n\nReplying to → {original_link}"
        final_answer = answer + footer

        if len(final_answer) > 2000:
            chunk_size = 1900
            answer_parts = [answer[i:i + chunk_size] for i in range(0, len(answer), chunk_size)]
            for i, part in enumerate(answer_parts):
                if i == len(answer_parts) - 1:
                    await interaction.followup.send(part + footer)
                else:
                    await interaction.followup.send(part + "\n\n...(continued)")
        else:
            await interaction.followup.send(final_answer)

    except Exception as e:
        logger.error(f"/research error: {e}")
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


# Reaction trigger: 🤖 on a message starts a research thread
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if str(payload.emoji) != "🤖":
        return
    if payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    if channel is None:
        return

    message = await channel.fetch_message(payload.message_id)
    logger.info(f"🤖 Reaction on message: {message.content[:80]}...")
    await do_research(message)


async def do_research(message: discord.Message):
    if message.author == bot.user:
        return

    original_link = message.jump_url

    thread = await message.create_thread(
        name=f"Research: {message.content[:50]}...",
        auto_archive_duration=1440,
    )

    await thread.send("🔍 Researching with Grok (live web search enabled)...")
    logger.info(f"Thread created for message: {message.id}")

    try:
        # Try main model, fallback if fails for model-related reasons
        try:
            answer = await research_query(message.content, original_link)
        except ValueError as e:
            if "Invalid model" in str(e) or "Grok API Error" in str(e):
                logger.warning(f"Main model failed ({e}), trying fallback: {FALLBACK_MODEL}")
                answer = await research_query(message.content, original_link, model=FALLBACK_MODEL)
            else:
                raise

        # Truncate if too long to avoid hitting Discord's 2000 char limit
        max_content_length = 1800  # Leave buffer for footer
        if len(answer) > max_content_length:
            answer = answer[:max_content_length] + "\n... (truncated)"

        footer = f"\n\nReplying to → {original_link}"
        final_answer = answer + footer

        # Split into Discord-safe chunks (2000 char limit)
        if len(final_answer) > 2000:
            chunk_size = 1900
            answer_parts = [answer[i:i + chunk_size] for i in range(0, len(answer), chunk_size)]
            for i, part in enumerate(answer_parts):
                if i == len(answer_parts) - 1:
                    await thread.send(part + footer)
                else:
                    await thread.send(part + "\n\n...(continued)")
        else:
            await thread.send(final_answer)

        await thread.send("✅ Grok research complete!")
        logger.info("Research complete and posted")

    except Exception as e:
        error_msg = f"❌ Error: {str(e)} (Check bot logs for details)"
        await thread.send(error_msg)
        logger.error(f"do_research error for message {message.id}: {e}")


# Webserver & main (health checks, status)
async def start_webserver(port: int = 8080):
    """Start a simple aiohttp web server for health checks and status."""
    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    async def status(request):
        return web.json_response({
            "bot": str(bot.user) if bot.user else None,
            "ready": bot.is_ready(),
            "model": GROK_MODEL,
        })

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Webserver started on 0.0.0.0:{port}")
    return runner


async def main():
    """Orchestrator: start webserver and discord bot concurrently."""
    port = int(os.getenv("PORT", "8080"))

    # Start webserver
    web_runner = await start_webserver(port)

    # Start bot
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.warning("DISCORD_TOKEN is not set — starting only the webserver. The bot will not run.")
        await asyncio.Event().wait()

    bot_task = asyncio.create_task(bot.start(token))

    try:
        await bot_task
    finally:
        await bot.close()
        await web_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
