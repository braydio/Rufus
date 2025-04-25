import discord
import requests
import json

TOKEN = "YOUR_DISCORD_BOT_TOKEN"
AI_API_URL = "http://localhost:5000/api/v1/generate"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
client = discord.Client(intents=intents)

def query_local_ai(prompt):
    payload = {
        "prompt": prompt,
        "max_new_tokens": 200,
        "temperature": 0.7,
    }
    response = requests.post(AI_API_URL, json=payload)
    result = response.json()
    return result['results'][0]['text'].strip()

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name == "ai-chat" or client.user.mentioned_in(message):
        prompt = message.content
        response = query_local_ai(prompt)
        await message.channel.send(response)

client.run(TOKEN)

