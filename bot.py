# bot.py
import discord
from discord.ext import commands
import os
import asyncio
import logging

from config import Config # Import the Config class
from utils.database_manager import DatabaseManager # For initializing DB schema if needed

# Configure logging
logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger('discord_bot')

# Define intents
# Ensure you have enabled Privileged Gateway Intents (Server Members, Message Content) in your bot's application page on Discord.
intents = discord.Intents.default()
intents.message_content = True # Required for reading message content if using prefix commands, or for some specific event handling.
intents.members = True # If you need to access member information beyond what's in cache.

class AIQuizBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = Config() # Make config accessible
        self.db_manager = None # Will be initialized in setup_hook

    async def setup_hook(self):
        """
        This is called when the bot is loading and before it connects to Discord.
        Use this to load cogs, initialize database connections, etc.
        """
        logger.info(f"Bot instance created. User: {self.user}")

        # Initialize DatabaseManager
        try:
            self.db_manager = DatabaseManager(
                supabase_url=self.config.SUPABASE_URL,
                supabase_key=self.config.SUPABASE_KEY
            )
            await self.db_manager.initialize() # Connect and potentially create tables
            logger.info("DatabaseManager initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize DatabaseManager: {e}")
            # Depending on the severity, you might want to prevent the bot from starting
            # For now, we'll let it start but log the error.

        # Load cogs
        cog_folders = ["cogs"] # Can add more subdirectories if needed
        for folder in cog_folders:
            for filename in os.listdir(folder):
                if filename.endswith(".py") and not filename.startswith("__"):
                    cog_name = f"{folder}.{filename[:-3]}"
                    try:
                        await self.load_extension(cog_name)
                        logger.info(f"Successfully loaded cog: {cog_name}")
                    except Exception as e:
                        logger.error(f"Failed to load cog {cog_name}: {e}", exc_info=True)
        
        # Sync application commands (slash commands)
        # It's generally recommended to sync commands selectively or use a command to sync.
        # For initial setup, syncing globally can be fine, but be mindful of rate limits.
        try:
            # If you want to sync to a specific guild for testing:
            # guild_id = int(self.config.YOUR_TEST_GUILD_ID) # Add YOUR_TEST_GUILD_ID to .env
            # self.tree.copy_global_to(guild=discord.Object(id=guild_id))
            # await self.tree.sync(guild=discord.Object(id=guild_id))
            # logger.info(f"Synced commands to guild {guild_id}")

            # Sync globally
            await self.tree.sync()
            logger.info("Synced application commands globally.")
        except Exception as e:
            logger.error(f"Failed to sync application commands: {e}")


    async def on_ready(self):
        """Called when the bot is fully connected and ready."""
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        logger.info(f"Discord.py version: {discord.__version__}")
        logger.info("AI Quiz Bot is ready and listening!")
        # You might want to set a custom presence
        await self.change_presence(activity=discord.Game(name="a quiz! Type /help"))

    async def on_command_error(self, ctx, error):
        """Global command error handler."""
        if isinstance(error, commands.CommandNotFound):
            # await ctx.send("Invalid command. Use `/help` to see available commands.")
            logger.warning(f"Command not found: {ctx.message.content}")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: {error.param.name}. Please check the command usage.")
        elif isinstance(error, commands.CommandInvokeError):
            logger.error(f"Error in command {ctx.command}: {error.original}", exc_info=True)
            await ctx.send("An error occurred while processing the command. The developers have been notified.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("You do not have the necessary permissions to use this command.")
        else:
            logger.error(f"Unhandled command error: {error}", exc_info=True)
            await ctx.send("An unexpected error occurred. Please try again later.")


if __name__ == "__main__":
    # Create bot instance
    # Using command_prefix is optional if you only plan to use slash commands.
    # If you want prefix commands too, define one.
    bot = AIQuizBot(command_prefix=commands.when_mentioned_or("!quiz "), intents=intents)
    
    # Run the bot
    try:
        bot.run(Config.DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.critical(f"Failed to start the bot: {e}", exc_info=True)

