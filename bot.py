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

# === GROK API CONFIG (NOW CONFIGURABLE) ===
API_URL = "https://api.x.ai/v1/chat/completions"
GROK_API_KEY = os.getenv("GROK_API_KEY")
if not GROK_API_KEY:
    raise ValueError("GROK_API_KEY environment variable is missing!")

headers = {
    "Authorization": f"Bearer {GROK_API_KEY}",
    "Content-Type": "application/json"
}

# Choose model via env var — these are the correct names as of Nov 2025
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-fast-thinking")  # ← Default: Grok-4 Fast Thinking

# Optional: list of valid models (for future reference)
VALID_MODELS = [
    "grok-4-fast-thinking",      # ← Best speed + reasoning (recommended)
    "grok-4",                    # Full Grok-4 (slower, smarter)
    "grok-3",                    # Previous gen
    "grok-beta",                 # Legacy
]

if GROK_MODEL not in VALID_MODELS:
    print(f"Warning: Using unknown model '{GROK_MODEL}' — hope you know what you're doing!")

# Tool definition (web search — still free until Dec 3, 2025)
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
- At the end, say "Replying to: {message_link}"
- Be concise but thorough."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    payload = {
        "model": GROK_MODEL,           # ← Now uses the correct configurable model
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
                    # Replace this with real search later (Tavily, Exa, Serper, etc.)
                    search_results = f"Mock search results for: '{args.get('query', '')}'\n• Result 1: https://example.com\n• Result 2: https://wikipedia.org"
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

# === Rest of your bot code (unchanged below) ===
@bot.event
async def on_ready():
    print(f"{bot.user} is online! Using model: {GROK_MODEL}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(e)

# [Your existing slash command, reaction handler, do_research, webserver, main() — all unchanged]

# ... [keep everything else exactly as you had it from do_research() down to main()]

# Just paste the rest of your original code here — no changes needed below this line