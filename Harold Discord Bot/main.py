import discord
from discord.ext import commands
import os
import re
import asyncio
from datetime import timedelta
import aiohttp
from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.


bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

discordAPI = os.getenv('DISCORD_TOKEN')
openAIKey = os.getenv('OPEN_AI_KEY')

# Store conversation history per channel: {channel_id: [messages]}
conversations = {}

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are Harold, a witty and helpful Discord bot. "
        "Keep your responses short — no more than 5 to 6 sentences at most, "
        "but shorter is usually better. Be concise and conversational. "
        "Always finish your thoughts completely — never leave a sentence unfinished."
    ),
}

# Max messages to keep in history per channel (not counting the system prompt)
MAX_HISTORY = 20

# Banned words filter
# Add any curse words or slurs to this set (all lowercase).
# The bot will mute & deafen any user in a voice channel who uses these words.
BANNED_WORDS = {
    "badword1", "nonoword",
}

# Build a regex pattern that matches any banned word as a whole word
_banned_pattern = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in BANNED_WORDS) + r')\b',
    re.IGNORECASE,
)

# Spam detection
# Track recent message timestamps per user: {user_id: [timestamps]}
_spam_tracker: dict[int, list[float]] = {}
SPAM_MSG_LIMIT = 5        # number of messages within the window to count as spam
SPAM_WINDOW_SECS = 5      # seconds window
SPAM_TIMEOUT_MINS = 5     # timeout duration in minutes
SPAM_ROLE_NAME = "timeout due to spamming messages"


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')


@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from bots (including ourselves)
    if message.author.bot:
        return

    # Spam detection
    import time
    member = message.author
    if isinstance(member, discord.Member):
        now = time.time()
        uid = member.id
        timestamps = _spam_tracker.setdefault(uid, [])
        timestamps.append(now)
        # Only keep timestamps within the window
        _spam_tracker[uid] = [
            t for t in timestamps if now - t <= SPAM_WINDOW_SECS]

        if len(_spam_tracker[uid]) >= SPAM_MSG_LIMIT:
            _spam_tracker[uid] = []  # reset so they don't get double-punished

            # Timeout the user
            try:
                await member.timeout(timedelta(minutes=SPAM_TIMEOUT_MINS),
                                     reason="Spamming messages")
            except discord.Forbidden:
                await message.channel.send(
                    "I don't have permission to timeout that user."
                )

            # Assign the spam timeout role
            spam_role = discord.utils.get(
                member.guild.roles, name=SPAM_ROLE_NAME)
            if spam_role:
                try:
                    await member.add_roles(spam_role)
                except discord.Forbidden:
                    pass
            else:
                await message.channel.send(
                    f'⚠️ The "{SPAM_ROLE_NAME}" role doesn\'t exist. Please create it.'
                )

            await message.channel.send(
                f"{member.mention} has been timed out for {SPAM_TIMEOUT_MINS} minutes for spamming."
            )

            # Auto-remove the role after the timeout expires
            async def _remove_spam_role(m=member, r=spam_role):
                await asyncio.sleep(SPAM_TIMEOUT_MINS * 60)
                if r and r in m.roles:
                    try:
                        await m.remove_roles(r)
                    except discord.Forbidden:
                        pass

            if spam_role:
                bot.loop.create_task(_remove_spam_role())

            # Process commands and return early, skip further checks for this message
            await bot.process_commands(message)
            return

    # Check for banned words
    if _banned_pattern.search(message.content):
        member = message.author

        # Server-mute and server-deafen if the user is in a voice channel
        if isinstance(member, discord.Member) and member.voice:
            try:
                await member.edit(mute=True, deafen=True)
            except discord.Forbidden:
                await message.channel.send(
                    "I don't have permission to mute/deafen that user."
                )

        # Assign the "exhiled" role and lock out of all channels
        if isinstance(member, discord.Member):
            jail_role = discord.utils.get(member.guild.roles, name="exhiled")
            if jail_role:
                try:
                    await member.add_roles(jail_role)
                except discord.Forbidden:
                    await message.channel.send(
                        "I don't have permission to assign the exhiled role."
                    )
            else:
                await message.channel.send(
                    "⚠️ The \"exhiled\" role doesn't exist in this server. Please create it."
                )

            # Remove access to every text and voice channel EXCEPT court channels
            deny_overwrite = discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                connect=False,
                speak=False,
            )
            allow_overwrite = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                connect=True,
                speak=True,
            )
            for channel in member.guild.channels:
                try:
                    if channel.name in ("court", "court-text"):
                        await channel.set_permissions(member, overwrite=allow_overwrite)
                    else:
                        await channel.set_permissions(member, overwrite=deny_overwrite)
                except discord.Forbidden:
                    pass

        await message.channel.send(
            f"{member.mention} has been exhiled for using inappropriate language."
        )

        # Delete the offending message
        try:
            await message.delete()
        except discord.Forbidden:
            pass

    # IMPORTANT: process commands so !gpt, !clear, etc. still work
    await bot.process_commands(message)


@bot.command()
async def gpt(ctx: commands.Context, *, prompt: str):
    """Chat with GPT. Conversation history is kept per channel."""
    openAIKey = os.getenv("OPEN_AI_KEY")

    if not openAIKey:
        await ctx.reply("OpenAI API key is not set. Please configure it.")
        return

    channel_id = ctx.channel.id

    # Initialise history for this channel if needed
    if channel_id not in conversations:
        conversations[channel_id] = []

    # Append the user's message
    conversations[channel_id].append({"role": "user", "content": prompt})

    # Trim history if it exceeds the limit
    if len(conversations[channel_id]) > MAX_HISTORY:
        conversations[channel_id] = conversations[channel_id][-MAX_HISTORY:]

    # Build the full message list: system prompt + conversation history
    messages = [SYSTEM_PROMPT] + conversations[channel_id]

    async with aiohttp.ClientSession() as session:
        payload = {
            'model': 'gpt-4o-mini',
            'messages': messages,
            'temperature': 0.9,
            'presence_penalty': 0,
            'frequency_penalty': 0,
        }
        headers = {'Authorization': f'Bearer {openAIKey}'}

        try:
            async with session.post('https://api.openai.com/v1/chat/completions', json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_details = await resp.text()
                    await ctx.reply(f"API Error: {resp.status}\nDetails: {error_details}")
                    return

                response = await resp.json()

                if 'choices' in response and len(response['choices']) > 0:
                    response_text = response['choices'][0]['message']['content'].strip(
                    )

                    # Save the assistant's reply to the conversation history
                    conversations[channel_id].append(
                        {"role": "assistant", "content": response_text})

                    embed = discord.Embed(
                        title="Harold says:",
                        description=response_text,
                    )
                    await ctx.reply(embed=embed)
                else:
                    await ctx.reply("No valid response received from the API.")
                    print("Unexpected API Response:", response)

        except Exception as e:
            await ctx.reply(f"An error occurred: {str(e)}")
            print(f"Exception: {e}")


@bot.command(name='clear')
async def clear(ctx: commands.Context):
    """Clear the conversation history for this channel."""
    channel_id = ctx.channel.id
    conversations.pop(channel_id, None)
    await ctx.reply("Conversation history cleared!")


@bot.command(name='unexhile')
async def unexhile(ctx: commands.Context, member: discord.Member):
    """Unexhile a user: unmute, undeafen, remove exhiled role, and restore channel access (owner only)."""
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.reply("Only the server owner can use this command.")
        return
    # Unmute and undeafen if in voice
    if member.voice:
        try:
            await member.edit(mute=False, deafen=False)
        except discord.Forbidden:
            await ctx.reply("I don't have permission to unmute/undeafen that user.")

    # Remove the exhiled role
    jail_role = discord.utils.get(ctx.guild.roles, name="exhiled")
    if jail_role and jail_role in member.roles:
        try:
            await member.remove_roles(jail_role)
        except discord.Forbidden:
            await ctx.reply("I don't have permission to remove the exhiled role.")

    # Remove per-user permission overwrites from all channels
    for channel in ctx.guild.channels:
        try:
            await channel.set_permissions(member, overwrite=None)
        except discord.Forbidden:
            pass

    await ctx.reply(f"{member.mention} has been unexhiled and access has been restored.")


@bot.command(name='hello')
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')


# ---- Poll command ----
TIME_OPTIONS = {
    "5m":  ("5 minutes", 5 * 60),
    "15m": ("15 minutes", 15 * 60),
    "30m": ("30 minutes", 30 * 60),
    "1h":  ("1 hour", 60 * 60),
    "1d":  ("1 day", 24 * 60 * 60),
}

NUMBER_EMOJIS = ["1\u20e3", "2\u20e3", "3\u20e3", "4\u20e3", "5\u20e3",
                 "6\u20e3", "7\u20e3", "8\u20e3", "9\u20e3", "\U0001f51f"]


@bot.command(name='poll')
async def poll(ctx: commands.Context, duration: str, question: str, *options: str):
    """Create a timed poll.

    Usage: !poll <duration> "question" "option1" "option2" ...
    Durations: 5m, 15m, 30m, 1h, 1d
    Provide 2–10 options.
    """
    duration_lower = duration.lower()
    if duration_lower not in TIME_OPTIONS:
        valid = ", ".join(TIME_OPTIONS.keys())
        await ctx.reply(f"Invalid duration. Choose one of: {valid}")
        return

    if len(options) < 2:
        await ctx.reply("You need at least 2 options. Wrap each option in quotes.")
        return
    if len(options) > 10:
        await ctx.reply("You can have at most 10 options.")
        return

    label, seconds = TIME_OPTIONS[duration_lower]

    description = "\n".join(
        f"{NUMBER_EMOJIS[i]}  {opt}" for i, opt in enumerate(options)
    )

    embed = discord.Embed(
        title=f"\U0001f4ca  {question}",
        description=description,
        color=discord.Color.blurple(),
    )
    embed.set_footer(
        text=f"Poll by {ctx.author.display_name} • Ends in {label}")

    poll_msg = await ctx.send("@everyone 📊 **New poll!**", embed=embed)

    for i in range(len(options)):
        await poll_msg.add_reaction(NUMBER_EMOJIS[i])

    # If the poll is longer than 5 minutes, send a reminder at the 5-minute mark
    five_minutes = 5 * 60
    if seconds > five_minutes:
        await asyncio.sleep(seconds - five_minutes)
        await ctx.send(f"@everyone ⏰ **There are five minutes left to answer the poll: \"{question}\"!**")
        await asyncio.sleep(five_minutes)
    else:
        await asyncio.sleep(seconds)

    # Re-fetch the message to get updated reaction counts
    try:
        poll_msg = await ctx.channel.fetch_message(poll_msg.id)
    except discord.NotFound:
        return

    # Tally results (subtract 1 for the bot's own reaction)
    results = []
    for i, opt in enumerate(options):
        reaction = discord.utils.get(
            poll_msg.reactions, emoji=NUMBER_EMOJIS[i])
        count = (reaction.count - 1) if reaction else 0
        results.append((opt, count))

    results.sort(key=lambda r: r[1], reverse=True)

    result_text = "\n".join(
        f"**{opt}** — {count} vote{'s' if count != 1 else ''}"
        for opt, count in results
    )

    result_embed = discord.Embed(
        title=f"\U0001f4ca  Poll Results: {question}",
        description=result_text,
        color=discord.Color.green(),
    )
    result_embed.set_footer(text=f"Poll by {ctx.author.display_name} • Ended")

    await ctx.send(embed=result_embed)

# Run the bot
bot.run(discordAPI)
