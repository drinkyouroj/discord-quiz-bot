# cogs/admin_cog.py
import discord
from discord.ext import commands
from discord import app_commands 
import logging

logger = logging.getLogger(__name__) # Get a logger for this cog

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("AdminCog __init__ called and instance created.")

    async def cog_load(self):
        logger.info("AdminCog cog_load method called.")

    # Renamed check function to avoid potential conflicts with stale registrations
    async def _is_authorized_admin(self, interaction: discord.Interaction) -> bool:
        """Checks if the interacting user is an admin based on ADMIN_USER_IDS or bot owner."""
        admin_ids = self.bot.config.ADMIN_USER_IDS 
        is_owner = await self.bot.is_owner(interaction.user)

        if not admin_ids: 
            if is_owner:
                logger.info(f"Admin check passed for {interaction.user} (ID: {interaction.user.id}): User is bot owner (ADMIN_USER_IDS not configured).")
                return True
            logger.warning(f"Admin check failed for {interaction.user} (ID: {interaction.user.id}): ADMIN_USER_IDS not configured and user is not bot owner.")
            # Send message only if not already responded (e.g. by a higher level check)
            if not interaction.response.is_done():
                await interaction.response.send_message("Admin IDs are not configured. This command is restricted.", ephemeral=True)
            return False

        if interaction.user.id in admin_ids or is_owner:
            logger.info(f"Admin check passed for {interaction.user} (ID: {interaction.user.id}). In admin_ids: {interaction.user.id in admin_ids}, Is_owner: {is_owner}")
            return True
        
        logger.warning(f"Admin check failed for {interaction.user} (ID: {interaction.user.id}): User not in ADMIN_USER_IDS and not bot owner.")
        if not interaction.response.is_done():
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return False

    @app_commands.command(name="resetscores", description="Ends current quiz session and starts a new one.")
    # Decorator remains commented out, check is manual
    # @app_commands.check(_is_authorized_admin) 
    async def reset_scores_command(self, interaction: discord.Interaction):
        logger.info(f"Command /resetscores invoked by {interaction.user} (ID: {interaction.user.id}).")
        # Manual check using the renamed method
        if not await self._is_authorized_admin(interaction): 
            return 
        
        # Defer response as the operation might take time.
        # Check if already responded by the auth check before deferring.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False) 
        else: # If auth check already sent an ephemeral message, we can't defer publicly.
              # This scenario needs careful handling if we want public responses after auth failure.
              # For now, if auth fails, it sends ephemeral and returns.
              # If auth passes, interaction is not responded to yet.
            pass


        game_manager = self.bot.get_cog("GameManagerCog")
        if not game_manager:
            logger.error("GameManagerCog not found for /resetscores.")
            # Use followup if deferred, otherwise edit original or send new
            if interaction.response.is_done():
                await interaction.followup.send("Error: GameManager module is not loaded. Cannot reset scores.", ephemeral=True)
            else: # Should not happen if defer is called after auth check
                await interaction.response.send_message("Error: GameManager module is not loaded. Cannot reset scores.", ephemeral=True)
            return

        try:
            session_message = await game_manager.start_new_quiz_session()
            if interaction.response.is_done():
                await interaction.followup.send(f"Scores have been reset! {session_message}")
            else: # Should not happen
                 await interaction.response.send_message(f"Scores have been reset! {session_message}")
            await game_manager.generate_and_post_new_question()
        except Exception as e:
            logger.error(f"Error during /resetscores: {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(f"An error occurred while resetting scores: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"An error occurred while resetting scores: {e}", ephemeral=True)


    @app_commands.command(name="skipquestion", description="Skips the current question and posts a new one.")
    # Decorator remains commented out
    # @app_commands.check(_is_authorized_admin)
    async def skip_question_command(self, interaction: discord.Interaction):
        logger.info(f"Command /skipquestion invoked by {interaction.user} (ID: {interaction.user.id}).")
        # Manual check using the renamed method
        if not await self._is_authorized_admin(interaction): 
            return
            
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        game_manager = self.bot.get_cog("GameManagerCog")
        if not game_manager:
            logger.error("GameManagerCog not found for /skipquestion.")
            if interaction.response.is_done():
                await interaction.followup.send("Error: GameManager module is not loaded. Cannot skip question.", ephemeral=True)
            else:
                await interaction.response.send_message("Error: GameManager module is not loaded. Cannot skip question.", ephemeral=True)
            return
        
        # Ensure current_question_message_id attribute exists
        current_q_msg_id = getattr(game_manager, 'current_question_message_id', None)
        if not current_q_msg_id: 
            if interaction.response.is_done():
                await interaction.followup.send("There is no active question to skip.", ephemeral=True)
            else:
                await interaction.response.send_message("There is no active question to skip.", ephemeral=True)
            return

        try:
            skipped_message = await game_manager.skip_current_question(admin_initiated=True)
            if interaction.response.is_done():
                await interaction.followup.send(f"Question skipped by admin. {skipped_message}")
            else:
                 await interaction.response.send_message(f"Question skipped by admin. {skipped_message}")
            await game_manager.generate_and_post_new_question()
        except Exception as e:
            logger.error(f"Error during /skipquestion: {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(f"An error occurred while skipping the question: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"An error occurred while skipping the question: {e}", ephemeral=True)

    # Generic error handler for app commands in this cog
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        logger.error(f"Error in AdminCog app command {interaction.command.name if interaction.command else 'unknown'}: {error}", exc_info=True)
        # Check if the error is due to our manual check failing (though _is_authorized_admin sends its own response)
        if isinstance(error, app_commands.CheckFailure):
            logger.warning(f"AdminCog command check failed for user {interaction.user.id}: {error}")
            # _is_authorized_admin should have already sent a message.
            # If not, or if another check failed:
            if not interaction.response.is_done():
                 await interaction.response.send_message("You do not have permission for this command.",ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
            logger.error(f"CommandInvokeError in AdminCog: {error.original}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred executing this admin command.", ephemeral=True)
            else: # If deferred
                await interaction.followup.send("An error occurred executing this admin command.", ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred with this admin command.", ephemeral=True)
            else:
                await interaction.followup.send("An unexpected error occurred with this admin command.", ephemeral=True)

async def setup(bot: commands.Bot):
    logger.info("Attempting to setup AdminCog...")
    try:
        cog_instance = AdminCog(bot)
        await bot.add_cog(cog_instance)
        logger.info("AdminCog setup complete and cog added to bot.")
    except Exception as e:
        logger.error(f"Failed during AdminCog setup or add_cog: {e}", exc_info=True)
        raise 
