# cogs/quiz_cog.py
import discord
from discord.ext import commands
from discord import app_commands 
import logging
import datetime # Ensure datetime is imported

logger = logging.getLogger(__name__) # Get a logger for this cog

class QuizCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("QuizCog __init__ called and instance created.")

    async def cog_load(self):
        logger.info("QuizCog cog_load method called.")

    @app_commands.command(name="answer", description="Submit your answer to the current quiz question.")
    async def answer_command(self, interaction: discord.Interaction, *, your_answer: str):
        logger.info(f"Command /answer invoked by {interaction.user} (ID: {interaction.user.id}) with answer: '{your_answer}'")
        await interaction.response.defer(ephemeral=True) 

        game_manager = self.bot.get_cog("GameManagerCog")
        if not game_manager:
            logger.error("GameManagerCog not found for /answer command.")
            await interaction.followup.send("Sorry, the quiz system is currently unavailable. Please try again later.", ephemeral=True)
            return

        if not getattr(game_manager, 'current_question_message_id', None) or not getattr(game_manager, 'active_session_id', None):
            await interaction.followup.send("There is no active quiz question or session right now. Please wait for an admin to start one.", ephemeral=True)
            return

        try:
            feedback_message = await game_manager.process_user_answer(interaction.user, your_answer)
            await interaction.followup.send(feedback_message, ephemeral=True) 
        except Exception as e:
            logger.error(f"Error processing answer for user {interaction.user.id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while processing your answer. Please try again.", ephemeral=True)


    @app_commands.command(name="leaderboard", description="Displays the leaderboard for the current quiz session.")
    async def leaderboard_command(self, interaction: discord.Interaction):
        logger.info(f"Command /leaderboard invoked by {interaction.user} (ID: {interaction.user.id}).")
        await interaction.response.defer(ephemeral=False) 

        db_manager = getattr(self.bot, 'db_manager', None)
        game_manager = self.bot.get_cog("GameManagerCog")

        if not db_manager:
            logger.error("DatabaseManager not found on bot instance for /leaderboard.")
            await interaction.followup.send("Leaderboard is currently unavailable. Database connection error.", ephemeral=True)
            return
        
        active_session_id = getattr(game_manager, 'active_session_id', None) if game_manager else None
        if not active_session_id:
            logger.warning("No active session ID found from GameManager for /leaderboard.")
            await interaction.followup.send("No active quiz session. The leaderboard is empty or an admin needs to start a new session with `/resetscores`.", ephemeral=True)
            return

        try:
            session_details = await db_manager.get_session_details(active_session_id)
            
            if not session_details:
                logger.warning(f"Could not retrieve details for active session ID {active_session_id}.")
                await interaction.followup.send(f"Could not retrieve details for session ID {active_session_id}. Leaderboard unavailable.", ephemeral=True)
                return

            scores = await db_manager.get_leaderboard(active_session_id, limit=10) 

            embed_title = f"Leaderboard - Quiz Session #{active_session_id}"
            
            start_time_str = "N/A"
            start_time_from_db = session_details.get('start_time')
            if start_time_from_db:
                if isinstance(start_time_from_db, str):
                    try:
                        # Attempt to parse ISO 8601 format, ensure it's timezone-aware (UTC)
                        dt_obj = datetime.datetime.fromisoformat(start_time_from_db.replace('Z', '+00:00'))
                        # Convert to UTC if it's not already (though fromisoformat with +00:00 should handle it)
                        dt_obj_utc = dt_obj.astimezone(datetime.timezone.utc)
                        start_time_str = dt_obj_utc.strftime('%Y-%m-%d %H:%M UTC')
                    except ValueError as ve:
                        logger.error(f"Could not parse start_time string '{start_time_from_db}' from DB for leaderboard: {ve}")
                        start_time_str = "Invalid date format" # Or keep as N/A
                elif hasattr(start_time_from_db, 'strftime'): # If it's already a datetime object
                    start_time_str = start_time_from_db.strftime('%Y-%m-%d %H:%M UTC')
                else:
                    logger.warning(f"Session start_time is not a string or datetime object: {type(start_time_from_db)}")
            
            footer_text = f"Session Started: {start_time_str}"


            if not scores:
                embed = discord.Embed(
                    title=embed_title,
                    description="No scores yet for this session. Be the first to answer correctly!",
                    color=discord.Color.blue()
                )
                embed.set_footer(text=footer_text)
                await interaction.followup.send(embed=embed)
                return

            embed = discord.Embed(title=embed_title, color=discord.Color.gold())
            embed.set_footer(text=footer_text)

            description_lines = []
            for rank, (user_id_str, score_value) in enumerate(scores, 1):
                try:
                    user_id_int = int(user_id_str) 
                    user = await self.bot.fetch_user(user_id_int) 
                    username = user.display_name if user else f"User ID: {user_id_str}"
                except (discord.NotFound, ValueError) as e:
                    logger.warning(f"Could not fetch user {user_id_str} for leaderboard: {e}")
                    username = f"User ID: {user_id_str}" 
                
                trophy = ""
                if rank == 1: trophy = "� "
                elif rank == 2: trophy = "🥈 "
                elif rank == 3: trophy = "🥉 "
                description_lines.append(f"{trophy}{rank}. {username}: {score_value} points")
            
            embed.description = "\n".join(description_lines) if description_lines else "Leaderboard is currently empty."
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error generating leaderboard: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while fetching the leaderboard.", ephemeral=True)
            
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        logger.error(f"Error in QuizCog app command {interaction.command.name if interaction.command else 'unknown'}: {error}", exc_info=True)
        if isinstance(error, app_commands.CommandInvokeError):
            logger.error(f"CommandInvokeError in QuizCog: {error.original}", exc_info=True)
        
        if not interaction.response.is_done():
            await interaction.response.send_message("An error occurred with this quiz command.", ephemeral=True)
        else:
            await interaction.followup.send("An error occurred with this quiz command.", ephemeral=True)

async def setup(bot: commands.Bot):
    logger.info("Attempting to setup QuizCog...")
    try:
        cog_instance = QuizCog(bot)
        await bot.add_cog(cog_instance)
        logger.info("QuizCog setup complete and cog added to bot.")
    except Exception as e:
        logger.error(f"Failed during QuizCog setup or add_cog: {e}", exc_info=True)
        raise 
