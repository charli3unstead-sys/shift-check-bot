import os
import time
import aiosqlite
import discord
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
LOG_CHANNEL_ID = int(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None

DB_PATH = os.getenv("DB_PATH", "/data/shifts.db")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_shifts (
                user_id INTEGER PRIMARY KEY,
                checkin_ts INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shift_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                checkin_ts INTEGER NOT NULL,
                checkout_ts INTEGER NOT NULL,
                duration_seconds INTEGER NOT NULL
            )
        """)
        await db.commit()


async def post_log(interaction, text):
    if LOG_CHANNEL_ID:
        channel = interaction.client.get_channel(LOG_CHANNEL_ID)
        if channel:
            if not interaction.response.is_done():
                await interaction.response.send_message("Done ✅", ephemeral=True)
            await channel.send(text)
            return
    await interaction.response.send_message(text, ephemeral=True)


@tree.command(name="checkin", description="Start your shift")
async def checkin(interaction: discord.Interaction):
    now = int(time.time())
    uid = interaction.user.id

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT checkin_ts FROM active_shifts WHERE user_id = ?", (uid,)
        )
        row = await cur.fetchone()
        if row:
            await interaction.response.send_message(
                f"⚠️ Already checked in since <t:{row[0]}:F>",
                ephemeral=True
            )
            return

        await db.execute(
            "INSERT INTO active_shifts (user_id, checkin_ts) VALUES (?, ?)",
            (uid, now)
        )
        await db.commit()

    await post_log(interaction, f"✅ {interaction.user.mention} checked in at <t:{now}:F>")


@tree.command(name="checkout", description="End your shift")
async def checkout(interaction: discord.Interaction):
    now = int(time.time())
    uid = interaction.user.id

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT checkin_ts FROM active_shifts WHERE user_id = ?", (uid,)
        )
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(
                "⚠️ You are not checked in.",
                ephemeral=True
            )
            return

        checkin_ts = row[0]
        duration = now - checkin_ts

        await db.execute("""
            INSERT INTO shift_history
            (user_id, checkin_ts, checkout_ts, duration_seconds)
            VALUES (?, ?, ?, ?)
        """, (uid, checkin_ts, now, duration))

        await db.execute(
            "DELETE FROM active_shifts WHERE user_id = ?", (uid,)
        )
        await db.commit()

    worked = format_duration(duration)
    await post_log(
        interaction,
        f"⏱ {interaction.user.mention} checked out\n"
        f"• Worked: **{worked}**"
    )


@client.event
async def on_ready():
    await init_db()
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    print(f"Logged in as {client.user}")


client.run(TOKEN)
