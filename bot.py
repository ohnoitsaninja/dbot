import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import aiohttp
from aiohttp import web
import json
from dotenv import load_dotenv
import logging  # ← Added for detailed logs

load_dotenv()

# Set up logging (visible in Render logs)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# === GROK API CONFIG (ACCURATE NOV 2025 MODELS) ===
API_URL = "https://api.x.ai/v1/chat/completions"
GROK_API_KEY = os.getenv("GROK_API_KEY")
if not GROK_API_KEY:
    raise ValueError("GROK_API_KEY environment variable is missing!")

headers = {
    "Authorization": f"Bearer {GROK_API_KEY}",
    "Content-Type": "application/json"
}

# Choose model via env var — defaults to Grok 4.1 Fast Reasoning (Nov 2025)
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-1-fast-reasoning")
FALLBACK_MODEL = "grok-4-1-fast-non-reasoning"  # ← Cheaper fallback during issues

# Valid models (official xAI API as of Nov 22, 2025)
VALID_MODELS = [
    "grok-4-1-fast-reasoning",       # Agentic tool-calling + reasoning (recommended for research)
    "grok-4-1-fast-non-reasoning",   # Fast creative/emotional generation
    "grok-code-fast-1",              # Code-focused tasks
]

if GROK_MODEL not in VALID_MODELS:
    raise ValueError(f"Invalid model '{GROK_MODEL}'. Must be one of: {', '.join(VALID_MODELS)}")

# Tool definition (web search — free until Dec 3, 2025)
tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for real-time information to ground your response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                    "num_results": {"type": "integer", "description": "Number of results (default 5)."}
                },
                "required": ["query"]
            }
        }
    }
]

async def research_query(query: str, message_link: str):
    logger.info(f"Starting Grok query for: {query[:50]}...")  # Log start
    system_prompt = f"""You are a helpful research assistant in a Discord thread.
The user asked: "{query}"

Rules:
- Use the web_search tool if you need real-time info (e.g., facts, news, prices, events).
- Always cite sources with links.
- Use markdown, bullet points, and code blocks when helpful.
- Keep your response under 1000 characters.
- At the end, say "Replying to: {message_link}"
- Be concise but thorough."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    payload = {
        "model": GROK_MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.7,
        "max_tokens": 1000  # ← Reduced to save credits/time
    }

    timeout = aiohttp.ClientTimeout(total=60)  # ← 60s timeout to prevent hangs
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            logger.info(f"Sending request to Grok API with model: {GROK_MODEL}")
            response = await session.post(API_URL, json=payload, headers=headers)
            logger.info(f"API Response status: {response.status}")  # Log status

            data = await response.json()

            if "choices" not in data or not data["choices"]:
                error_msg = data.get("error", {}).get("message", "Unknown API error")
                logger.error(f"API Error details: {error_msg}")
                raise ValueError(f"Grok API Error: {error_msg} (Status: {response.status})")

            choice = data["choices"][0]["message"]
            messages.append(choice)

            # Handle tool calls (web search)
            if "tool_calls" in choice:
                logger.info("Tool call detected (web_search)")
                for tool_call in choice["tool_calls"]:
                    if tool_call["function"]["name"] == "web_search":
                        args = json.loads(tool_call["function"]["arguments"])
                        # Mock for now with placeholder results
                        search_results = f"""Search results for '{args.get('query', '')}':
- [Source 1] Recent news on topic: https://example-news.com/article1
- [Source 2] Wikipedia summary: https://en.wikipedia.org/wiki/{args.get('query', '').lower().replace(' ', '_')}
- [Source 3] Official site: https://official-source.org"""
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": search_results
                        })
                        payload["messages"] = messages
                        # Retry with tool response
                        response = await session.post(API_URL, json=payload, headers=headers)
                        data = await response.json()
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

# Slash command (unchanged, but added log)
@bot.tree.command(name="research", description="Start a research thread about a message")
@app_commands.describe(message="The message to research (message URL or content)")
async def research_slash(interaction: discord.Interaction, message: str):
    await interaction.response.defer()
    logger.info(f"Slash command triggered with: {message[:50]}...")
    # ... (rest unchanged)

# Reaction trigger (added log)
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.emoji) != "🤖":
        return
    if payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    logger.info(f"🤖 Reaction on message: {message.content[:50]}...")
    await do_research(message)

async def do_research(message: discord.Message):
    if message.author == bot.user:
        return

    original_link = message.jump_url

    thread = await message.create_thread(
        name=f"Research: {message.content[:50]}...",
        auto_archive_duration=1440
    )

    await thread.send("🔍 Researching with Grok... Please wait 10–30 seconds.")
    logger.info(f"Thread created for message: {message.id}")

    try:
        # Try main model, fallback if fails
        try:
            answer = await research_query(message.content, original_link)
        except ValueError as e:
            if "Invalid model" in str(e) or "Grok API Error" in str(e):
                logger.warning(f"Main model failed ({e}), trying fallback: {FALLBACK_MODEL}")
                payload["model"] = FALLBACK_MODEL  # Reuse payload from function if needed
                answer = await research_query(message.content, original_link)  # Retry with fallback
            else:
                raise

        # Truncate if too long to avoid hitting Discord's 2000 char limit
        max_content_length = 1800  # Leave buffer for footer
        if len(answer) > max_content_length:
            answer = answer[:max_content_length] + "\n... (truncated)"

        # Build message with footer
        footer = f"\n\nReplying to → {original_link}"
        final_answer = answer + footer

        # Split into Discord-safe chunks (2000 char limit)
        if len(final_answer) > 2000:
            # Split the answer part (without footer) and re-add footer to each part
            chunk_size = 1900
            answer_parts = [answer[i:i+chunk_size] for i in range(0, len(answer), chunk_size)]
            for i, part in enumerate(answer_parts):
                if i == len(answer_parts) - 1:
                    # Last chunk: add footer
                    await thread.send(part + footer)
                else:
                    # Not last chunk: add continuation indicator
                    await thread.send(part + "\n\n...(continued)")
        else:
            await thread.send(final_answer)

        await thread.send("✅ Grok research complete!")
        logger.info("Research complete and posted")

    except Exception as e:
        error_msg = f"❌ Error: {str(e)} (Check bot logs for details)"
        await thread.send(error_msg)
        logger.error(f"do_research error for message {message.id}: {e}")

# Webserver & main (unchanged)
async def start_webserver(port: int = 8080):
    """Start a simple aiohttp web server for health checks and status."""
    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    async def status(request):
        # return bot presence and online state
        return web.json_response({
            "bot": str(bot.user) if bot.user else None,
            "ready": bot.is_ready(),
            "model": GROK_MODEL
        })

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Webserver started on 0.0.0.0:{port}")
    return runner

async def main():
    """Orchestrator: start webserver and discord bot concurrently."""
    port = int(os.getenv("PORT", "8080"))

    # start webserver
    web_runner = await start_webserver(port)

    # start bot in background
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.warning("DISCORD_TOKEN is not set — starting only the webserver. The bot will not run.")
        # keep running so Render health checks pass
        await asyncio.Event().wait()

    bot_task = asyncio.create_task(bot.start(token))

    try:
        await bot_task
    finally:
        await bot.close()
        await web_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())