# Rufus Discord Bot

Rufus is a lightweight Discord bot that forwards prompts to an AI completion
endpoint and replies with an upbeat surf-coach personality. The project keeps a
single focus: provide a friendly conversational experience without the previous
TUI, scheduler, or watchlist code that had accumulated over time.

## Features

- Responds to messages prefixed with `..ai` (configurable via `COMMAND_PREFIX`).
- Sends chat-completion requests to an OpenAI-compatible endpoint.
- Keeps a small amount of channel-specific conversation history for context.
- Splits long replies into Discord-safe message chunks automatically.

## Getting Started

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Provide the following environment variables (use a `.env` file locally):

   - `BOT_TOKEN`: Discord bot token.
   - `API_URL`: Completion endpoint (defaults to `http://localhost:5051/v1/chat/completions`).
   - `MODEL`: Optional model name to include in the request payload.
   - `COMMAND_PREFIX`: Command prefix (defaults to `..ai`).

3. Run the bot:

   ```bash
   python main.py
   ```

When the bot is running in a server, type `..ai <your question>` and Rufus will
reply with a stoked, surfer-inspired answer.

## Project Structure

```
├── README.md
├── main.py
└── requirements.txt
```

This lean layout makes it easy to maintain and extend the bot without carrying
legacy artifacts from previous experiments.
