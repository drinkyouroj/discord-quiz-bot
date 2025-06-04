# cogs/quiz_cog.py
import discord
from discord.ext import commands
from discord import app_commands # For slash commands
import logging

logger = logging.getLogger(__name__)

class QuizCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("QuizCog initialized.")

    @app_commands.command(name="answer", description="Submit your answer to the current quiz question.")
    async def answer_command(self, interaction: discord.Interaction, *, your_answer: str):
        """
        Command for users to submit their answers.
        """
        logger.debug(f"User {interaction.user} (ID: {interaction.user.id}) submitted answer: '{your_answer}'")
        await interaction.response.defer(ephemeral=True) # Acknowledge, processing might take time, ephemeral for privacy

        game_manager = self.bot.get_cog("GameManagerCog")
        if not game_manager:
            logger.error("GameManagerCog not found for /answer command.")
            await interaction.followup.send("Sorry, the quiz system is currently unavailable. Please try again later.", ephemeral=True)
            return

        if not game_manager.current_question_message_id or not game_manager.active_session_id:
            await interaction.followup.send("There is no active quiz question or session right now. Please wait for an admin to start one.", ephemeral=True)
            return

        try:
            # Delegate answer processing to GameManagerCog
            # GameManagerCog will handle sending public feedback if needed
            feedback_message = await game_manager.process_user_answer(interaction.user, your_answer)
            await interaction.followup.send(feedback_message, ephemeral=True) # Send private feedback to user

        except Exception as e:
            logger.error(f"Error processing answer for user {interaction.user.id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while processing your answer. Please try again.", ephemeral=True)


    @app_commands.command(name="leaderboard", description="Displays the leaderboard for the current quiz session.")
    async def leaderboard_command(self, interaction: discord.Interaction):
        """
        Command to display the quiz leaderboard.
        """
        logger.debug(f"User {interaction.user} (ID: {interaction.user.id}) requested leaderboard.")
        await interaction.response.defer(ephemeral=False) # Public command

        db_manager = self.bot.db_manager # Access initialized DB manager
        game_manager = self.bot.get_cog("GameManagerCog")

        if not db_manager:
            logger.error("DatabaseManager not found for /leaderboard.")
            await interaction.followup.send("Leaderboard is currently unavailable. Database connection error.", ephemeral=True)
            return
        
        if not game_manager or not game_manager.active_session_id:
            await interaction.followup.send("No active quiz session. The leaderboard is empty or an admin needs to start a new session with `/resetscores`.", ephemeral=True)
            return

        try:
            current_session_id = game_manager.active_session_id
            session_details = await db_manager.get_session_details(current_session_id)
            
            if not session_details:
                await interaction.followup.send(f"Could not retrieve details for session ID {current_session_id}. Leaderboard unavailable.", ephemeral=True)
                return

            scores = await db_manager.get_leaderboard(current_session_id, limit=10) # Get top 10 for example

            if not scores:
                embed = discord.Embed(
                    title=f"Leaderboard - Quiz Session #{current_session_id}",
                    description="No scores yet for this session. Be the first to answer correctly!",
                    color=discord.Color.blue()
                )
                if session_details.get('start_time'):
                    embed.set_footer(text=f"Session Started: {session_details['start_time'].strftime('%Y-%m-%d %H:%M UTC')}")
                await interaction.followup.send(embed=embed)
                return

            embed = discord.Embed(
                title=f"Leaderboard - Quiz Session #{current_session_id}",
                color=discord.Color.gold()
            )
            if session_details.get('start_time'):
                 embed.set_footer(text=f"Session Started: {session_details['start_time'].strftime('%Y-%m-%d %H:%M UTC')}")


            description_lines = []
            for rank, (user_id, score_value) in enumerate(scores, 1):
                try:
                    user = await self.bot.fetch_user(int(user_id)) # Fetch user for display name
                    username = user.display_name if user else f"User ID: {user_id}"
                except (discord.NotFound, ValueError):
                    username = f"User ID: {user_id}" # Fallback if user not found or ID is not int
                
                trophy = ""
                if rank == 1: trophy = "🥇 "
                elif rank == 2: trophy = "🥈 "
                elif rank == 3: trophy = "🥉 "
                description_lines.append(f"{trophy}{rank}. {username}: {score_value} points")
            
            embed.description = "\n".join(description_lines)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error generating leaderboard: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while fetching the leaderboard.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(QuizCog(bot))
    logger.info("QuizCog added to bot.")

