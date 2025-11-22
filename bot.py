import discord
from discord import app_commands
from discord.ext import commands
import os
import asyncio
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Grok API config
API_URL = "https://api.x.ai/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {os.getenv('GROK_API_KEY')}",
    "Content-Type": "application/json"
}

# Tool definition for web search (Grok can call this automatically)
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
- Use the web_search tool if you need real-time info (e.g., facts, news).
- Always cite sources with links from search results.
- Use markdown, bullet points, and code blocks when helpful.
- At the end, say "Replying to: {message_link}"
- Be concise but thorough."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    payload = {
        "model": "grok-beta",  # Or "grok-2-latest" if available
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",  # Let Grok decide when to use search
        "temperature": 0.7,
        "max_tokens": 4000
    }

    # Handle tool calls (Grok might request search)
    async with aiohttp.ClientSession() as session:
        response = await session.post(API_URL, json=payload, headers=headers)
        data = await response.json()

        if "choices" not in data or not data["choices"]:
            raise ValueError(f"API Error: {data.get('error', 'Unknown')}")

        choice = data["choices"][0]["message"]
        messages.append(choice)  # Add assistant's message

        # If tool calls, execute and loop back
        if "tool_calls" in choice:
            for tool_call in choice["tool_calls"]:
                if tool_call["function"]["name"] == "web_search":
                    args = json.loads(tool_call["function"]["arguments"])
                    # Simulate search here (in prod, call a real search API like Tavily or Exa)
                    # For now, placeholder: fetch mock results or integrate a free search API
                    search_results = f"Mock search for '{args['query']}': Results from web [cite links here]."
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": search_results
                    })
                    # Re-call API with updated messages
                    payload["messages"] = messages
                    response = await session.post(API_URL, json=payload, headers=headers)
                    data = await response.json()
                    choice = data["choices"][0]["message"]

        return choice["content"]

@bot.event
async def on_ready():
    print(f"{bot.user} is online!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(e)

# Slash command (unchanged)
@bot.tree.command(name="research", description="Start a research thread about a message")
@app_commands.describe(message="The message to research")
async def research_slash(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer()
    await do_research(message)

# Reaction trigger (unchanged)
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.emoji) != "🤖":
        return
    if payload.user_id == bot.user.id:  # Fixed: use user_id
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

        # Split long answers (unchanged)
        if len(answer) > 2000:
            parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
            for i, part in enumerate(parts):
                if i == len(parts)-1:
                    await thread.send(part + f"\n\n[Continued]\nReplying to → {original_link}")
                else:
                    await thread.send(part + "\n\n...(continued)")
        else:
            await thread.send(answer + f"\n\nReplying to → {original_link}")

        await thread.send("✅ Grok research complete!")

    except Exception as e:
        await thread.send(f"❌ Error: {e}")

bot.run(os.getenv("DISCORD_TOKEN"))