import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import aiohttp
from aiohttp import web
import json
from dotenv import load_dotenv

load_dotenv()

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
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-1-fast-reasoning")  # ← Fast thinking/reasoning default

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
        "model": GROK_MODEL,           # ← Uses accurate Grok 4.1 model
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.7,
        "max_tokens": 4000
    }

    async with aiohttp.ClientSession() as session:
        response = await session.post(API_URL, json=payload, headers=headers)
        data = await response.json()

        if "choices" not in data or not data["choices"]:
            error_msg = data.get("error", {}).get("message", "Unknown API error")
            raise ValueError(f"Grok API Error: {error_msg}")

        choice = data["choices"][0]["message"]
        messages.append(choice)

        # Handle tool calls (web search)
        if "tool_calls" in choice:
            for tool_call in choice["tool_calls"]:
                if tool_call["function"]["name"] == "web_search":
                    args = json.loads(tool_call["function"]["arguments"])
                    # TODO: Integrate real API (e.g., Tavily, Exa) here
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
                    response = await session.post(API_URL, json=payload, headers=headers)
                    data = await response.json()
                    choice = data["choices"][0]["message"]

        return choice.get("content", "No response content.")

@bot.event
async def on_ready():
    print(f"{bot.user} is online! Using model: {GROK_MODEL}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(e)

# Slash command
@bot.tree.command(name="research", description="Start a research thread about a message")
@app_commands.describe(message="The message to research (message URL or content)")
async def research_slash(interaction: discord.Interaction, message: str):
    await interaction.response.defer()
    # If a link was provided, try to fetch the message
    try:
        if message.startswith("https://"):
            # URL format: https://discord.com/channels/<guild_id>/<channel_id>/<message_id>
            parts = message.split("/")
            message_id = int(parts[-1])
            channel_id = int(parts[-2])
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                msg = await channel.fetch_message(message_id)
                await do_research(msg)
                return
    except Exception:
        # fallback to using content directly
        pass

    # fallback: create a fake message-like object
    class _FakeMsg:
        def __init__(self, content, author, guild, jump_url=""):
            self.content = content
            self.author = author
            self.guild = guild
            self.jump_url = jump_url

    fake_message = _FakeMsg(content=message, author=interaction.user, guild=interaction.guild, jump_url="")
    await do_research(fake_message)

# Reaction trigger
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.emoji) != "🤖":
        return
    if payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
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

    try:
        answer = await research_query(message.content, original_link)

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

    except Exception as e:
        await thread.send(f"❌ Error: {e}")

async def start_webserver(port: int = 8080):
    """Start a simple aiohttp web server for health checks and status."""
    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    async def status(request):
        # return bot presence and online state
        return web.json_response({
            "bot": str(bot.user) if bot.user else None,
            "ready": bot.is_ready()
        })

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/status", status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Webserver started on 0.0.0.0:{port}")
    return runner

async def main():
    """Orchestrator: start webserver and discord bot concurrently."""
    port = int(os.getenv("PORT", "8080"))

    # start webserver
    web_runner = await start_webserver(port)

    # start bot in background
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("DISCORD_TOKEN is not set — starting only the webserver. The bot will not run.")
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