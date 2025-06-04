# bot.py
import discord
from discord.ext import commands
import os
import asyncio
import logging

from config import Config # Import the Config class
from utils.database_manager import DatabaseManager # For initializing DB schema if needed

# Configure logging
# Ensure this is one of the first things to run to capture all logs
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s %(levelname)-8s %(name)-15s %(message)s', # Added more detailed format
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('discord_bot') # Main bot logger

# Define intents
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

class AIQuizBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = Config() 
        self.db_manager = None 
        logger.info(f"AIQuizBot class __init__ called. Command prefix: '{self.command_prefix}'")

    async def setup_hook(self):
        """
        This is called when the bot is loading and before it connects to Discord.
        """
        logger.info(f"Setup_hook started. User: {self.user}") # self.user might be None here initially

        # Initialize DatabaseManager
        try:
            logger.info("Initializing DatabaseManager...")
            self.db_manager = DatabaseManager(
                supabase_url=self.config.SUPABASE_URL,
                supabase_key=self.config.SUPABASE_KEY
            )
            await self.db_manager.initialize() 
            logger.info("DatabaseManager initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize DatabaseManager: {e}", exc_info=True)
            # Decide if bot should stop: raise SystemExit("Database initialization failed.")

        # Load cogs
        cog_folders = ["cogs"] 
        logger.info(f"Loading cogs from folders: {cog_folders}")
        for folder in cog_folders:
            if not os.path.isdir(folder):
                logger.error(f"Cog folder '{folder}' not found. Skipping.")
                continue
            for filename in os.listdir(folder):
                if filename.endswith(".py") and not filename.startswith("__"):
                    cog_name = f"{folder}.{filename[:-3]}"
                    logger.info(f"Attempting to load extension: {cog_name}")
                    try:
                        await self.load_extension(cog_name)
                        logger.info(f"Successfully loaded extension: {cog_name}")
                    except commands.ExtensionAlreadyLoaded:
                        logger.warning(f"Extension already loaded: {cog_name}")
                    except commands.ExtensionNotFound:
                        logger.error(f"Extension not found: {cog_name}", exc_info=True)
                    except commands.NoEntryPointError:
                        logger.error(f"Extension has no setup function: {cog_name}", exc_info=True)
                    except commands.ExtensionFailed as e:
                        logger.error(f"Extension {cog_name} failed during setup or execution: {e.original}", exc_info=True)
                    except Exception as e:
                        logger.error(f"Generic error loading extension {cog_name}: {e}", exc_info=True)
        
        logger.info("Attempting to sync application commands...")
        try:
            # For testing, you might want to sync to a specific guild first
            # test_guild_id = os.getenv("TEST_GUILD_ID")
            # if test_guild_id:
            #     guild = discord.Object(id=int(test_guild_id))
            #     self.tree.copy_global_to(guild=guild)
            #     await self.tree.sync(guild=guild)
            #     logger.info(f"Synced application commands to test guild {test_guild_id}.")
            # else:
            #     await self.tree.sync()
            #     logger.info("Synced application commands globally.")
            
            await self.tree.sync() # Sync globally
            logger.info("Application commands synced globally.")
        except Exception as e:
            logger.error(f"Failed to sync application commands: {e}", exc_info=True)
        logger.info("Setup_hook finished.")


    async def on_ready(self):
        """Called when the bot is fully connected and ready."""
        # self.user should be available here
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        logger.info(f"Discord.py version: {discord.__version__}")
        logger.info(f"Connected to {len(self.guilds)} guilds.")
        logger.info("AI Quiz Bot is ready and listening!")
        
        # Set custom presence
        try:
            await self.change_presence(activity=discord.Game(name="a quiz! Use /commands"))
            logger.info("Bot presence updated.")
        except Exception as e:
            logger.error(f"Failed to set bot presence: {e}", exc_info=True)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Global command error handler for prefix commands."""
        logger.error(f"Prefix command error in command '{ctx.command}': {error}", exc_info=True)
        if isinstance(error, commands.CommandNotFound):
            # await ctx.send("Invalid command. Use `/help` to see available commands.")
            logger.warning(f"Prefix command not found: {ctx.message.content}")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument for `{ctx.command}`: {error.param.name}. Please check command usage.", ephemeral=True)
        elif isinstance(error, commands.CommandInvokeError):
            await ctx.send(f"An error occurred with `{ctx.command}`. Devs notified.", ephemeral=True)
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("You don't have permission for that prefix command.", ephemeral=True)
        else:
            await ctx.send("An unexpected error occurred with a prefix command.", ephemeral=True)


if __name__ == "__main__":
    logger.info("Starting AI Quiz Bot...")
    bot = AIQuizBot(command_prefix=commands.when_mentioned_or("!quiz "), intents=intents)
    
    try:
        bot.run(Config.DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        logger.critical("CRITICAL: Failed to log in. Check DISCORD_BOT_TOKEN.", exc_info=True)
    except Exception as e:
        logger.critical(f"CRITICAL: Bot failed to start or run: {e}", exc_info=True)
    logger.info("AI Quiz Bot has shut down.")
