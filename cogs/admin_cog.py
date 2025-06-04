# cogs/admin_cog.py
import discord
from discord.ext import commands
from discord import app_commands # For slash commands
import logging

# Assuming your bot instance is passed or accessible, e.g., via self.bot
# from config import config # If needed directly

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("AdminCog initialized.")

    # Helper function to check if the user is an admin
    # This uses the ADMIN_USER_IDS from config.py
    # You might want a more sophisticated role-based check in a real server
    async def is_admin(self, interaction: discord.Interaction) -> bool:
        """Checks if the interacting user is an admin based on ADMIN_USER_IDS."""
        # Access config through self.bot.config if set up in bot.py
        admin_ids = self.bot.config.ADMIN_USER_IDS 
        if not admin_ids: # If no admin IDs are configured, deny by default for safety
            await interaction.response.send_message("Admin IDs are not configured. This command is disabled.", ephemeral=True)
            return False
        if interaction.user.id not in admin_ids:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return False
        return True

    @app_commands.command(name="resetscores", description="Ends current quiz session and starts a new one.")
    @app_commands.check(is_admin) # Restrict to admins
    async def reset_scores_command(self, interaction: discord.Interaction):
        """
        Command to reset scores, end the current quiz session, and start a new one.
        """
        logger.info(f"User {interaction.user} (ID: {interaction.user.id}) initiated /resetscores.")
        await interaction.response.defer(ephemeral=False) # Acknowledge command, can take time

        game_manager = self.bot.get_cog("GameManagerCog")
        if not game_manager:
            logger.error("GameManagerCog not found.")
            await interaction.followup.send("Error: GameManager module is not loaded. Cannot reset scores.", ephemeral=True)
            return

        try:
            session_message = await game_manager.start_new_quiz_session()
            await interaction.followup.send(f"Scores have been reset! {session_message}")
            
            # Trigger the first question of the new session
            await game_manager.generate_and_post_new_question()

        except Exception as e:
            logger.error(f"Error during /resetscores: {e}", exc_info=True)
            await interaction.followup.send(f"An error occurred while resetting scores: {e}", ephemeral=True)

    @app_commands.command(name="skipquestion", description="Skips the current question and posts a new one.")
    @app_commands.check(is_admin) # Restrict to admins
    async def skip_question_command(self, interaction: discord.Interaction):
        """
        Command to skip the current active question.
        """
        logger.info(f"User {interaction.user} (ID: {interaction.user.id}) initiated /skipquestion.")
        await interaction.response.defer(ephemeral=False)

        game_manager = self.bot.get_cog("GameManagerCog")
        if not game_manager:
            logger.error("GameManagerCog not found.")
            await interaction.followup.send("Error: GameManager module is not loaded. Cannot skip question.", ephemeral=True)
            return
        
        if not game_manager.current_question_message_id:
            await interaction.followup.send("There is no active question to skip.", ephemeral=True)
            return

        try:
            skipped_message = await game_manager.skip_current_question(admin_initiated=True)
            await interaction.followup.send(f"Question skipped by admin. {skipped_message}")
            
            # Trigger next question
            await game_manager.generate_and_post_new_question()

        except Exception as e:
            logger.error(f"Error during /skipquestion: {e}", exc_info=True)
            await interaction.followup.send(f"An error occurred while skipping the question: {e}", ephemeral=True)

    @reset_scores_command.error
    @skip_question_command.error
    async def on_admin_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            # The check itself already sends a message, so we might not need to do anything here
            # or we can log it.
            logger.warning(f"Admin command check failed for user {interaction.user.id}: {error}")
        else:
            logger.error(f"Error in admin command: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred with this admin command.", ephemeral=True)
            else:
                await interaction.followup.send("An unexpected error occurred with this admin command.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
    logger.info("AdminCog added to bot.")

