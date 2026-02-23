# HaroldDiscordBotAI

HaroldBot is a Discord bot that you can add to your server. It handles AI-powered chat, timed polls, and automatic moderation — all from simple commands.

## Features

### AI Chat (`!gpt`)

Talk to Harold using OpenAI's GPT-4o-mini model. Conversation history is kept per channel (up to 20 messages) so Harold remembers context. Use `!clear` to reset the conversation.

### Timed Polls (`!poll`)

Create reaction-based polls with 2–10 options and a configurable duration (5m, 15m, 30m, 1h, or 1d). The bot pings @everyone, adds numbered reactions for voting, sends a 5-minute warning before the poll ends, and posts the final results.

### Auto-Moderation

- **Spam Detection** — If a user sends 5+ messages within 5 seconds, they are automatically timed out for 5 minutes and given a spam role.
- **Banned Words Filter** — Messages containing banned words are deleted. The offending user is server-muted, server-deafened, assigned the "exhiled" role, and locked out of all channels except designated court channels.

### Moderation Commands

- `!unexhile @user` — Restores a punished user by unmuting, undeafening, removing the "exhiled" role, and resetting channel permissions. **Server owner only.**

### Utility Commands

- `!hello` — Harold says hello back.
- `!clear` — Clears the GPT conversation history for the current channel.

## Setup

1. Clone the repository
2. Create a `.env` file with your tokens:
   ```
   DISCORD_TOKEN=your_discord_token
   OPEN_AI_KEY=your_openai_api_key
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run the bot:
   ```
   python main.py
   ```

## Server Requirements

The following roles and channels should exist in your Discord server for full functionality:

- **Roles:** `exhiled`, `timeout due to spamming messages`
- **Channels:** `court`, `court-text` (these remain accessible to exhiled users)
