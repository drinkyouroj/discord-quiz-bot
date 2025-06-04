# cogs/game_manager_cog.py
import discord
from discord.ext import commands, tasks
import asyncio
import random
import logging
import datetime # For timezone aware datetime objects

# Assuming your bot instance is passed or accessible
from config import config # For game settings
from utils.openai_client import OpenAIClient
# DatabaseManager will be accessed via self.bot.db_manager

logger = logging.getLogger(__name__)

class GameManagerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.openai_client = OpenAIClient(api_key=config.OPENAI_API_KEY)
        self.active_session_id = None
        
        # Current question state
        self.current_question_text = None
        self.current_question_intended_answer = None
        self.current_question_difficulty = None # "basic", "intermediate", "advanced"
        self.current_question_points = 0
        self.current_question_message_id = None # ID of the message displaying the question
        self.current_question_post_time = None # When the question was posted
        
        self.user_attempts = {} # {question_message_id: {user_id: attempts_count}}
        self.question_answered_by = None # user_id of the first correct/partial answerer

        self.quiz_channel = None # Will be fetched on ready or session start

        self.question_inactivity_timer.start() # Start the background task
        logger.info("GameManagerCog initialized.")

    async def cog_load(self):
        # This method is called when the cog is loaded.
        # Ensure quiz_channel is fetched.
        if config.QUIZ_CHANNEL_ID:
            await self.bot.wait_until_ready() # Ensure bot is connected
            self.quiz_channel = self.bot.get_channel(config.QUIZ_CHANNEL_ID)
            if not self.quiz_channel:
                logger.error(f"Could not find QUIZ_CHANNEL_ID: {config.QUIZ_CHANNEL_ID}. GameManager may not function correctly.")
            else:
                logger.info(f"GameManager will use quiz channel: {self.quiz_channel.name} (ID: {self.quiz_channel.id})")
        else:
            logger.warning("QUIZ_CHANNEL_ID not set. GameManager will not be able to post questions automatically.")
            
    def cog_unload(self):
        self.question_inactivity_timer.cancel()
        logger.info("GameManagerCog unloaded, inactivity timer cancelled.")

    async def _get_quiz_channel(self) -> discord.TextChannel | None:
        """Ensures the quiz channel is available."""
        if not self.quiz_channel and config.QUIZ_CHANNEL_ID:
            self.quiz_channel = self.bot.get_channel(config.QUIZ_CHANNEL_ID)
            if not self.quiz_channel:
                logger.error(f"Re-fetch failed: Could not find QUIZ_CHANNEL_ID: {config.QUIZ_CHANNEL_ID}.")
        if not self.quiz_channel:
             logger.warning("Quiz channel is not set or found. Cannot post messages.")
        return self.quiz_channel

    async def start_new_quiz_session(self) -> str:
        """
        Ends the current session (if any) and starts a new one.
        Returns a message string for confirmation.
        """
        db_manager = self.bot.db_manager
        if not db_manager:
            raise ConnectionError("DatabaseManager not available.")

        if self.active_session_id:
            await db_manager.end_quiz_session(self.active_session_id)
            logger.info(f"Ended quiz session: {self.active_session_id}")
        
        self.active_session_id = await db_manager.create_quiz_session()
        logger.info(f"Started new quiz session: {self.active_session_id}")
        
        # Reset game state for the new session
        self._reset_question_state()
        
        session_details = await db_manager.get_session_details(self.active_session_id)
        start_time_str = session_details['start_time'].strftime('%Y-%m-%d %H:%M UTC') if session_details else "N/A"

        return f"New quiz session #{self.active_session_id} has started at {start_time_str}!"

    def _reset_question_state(self, clear_message_id=True):
        """Resets variables related to the current question."""
        self.current_question_text = None
        self.current_question_intended_answer = None
        self.current_question_difficulty = None
        self.current_question_points = 0
        if clear_message_id: # Only clear if we are truly done with the old question message
             self.current_question_message_id = None
        self.current_question_post_time = None
        self.user_attempts.clear() # Clear attempts for the new question context
        self.question_answered_by = None
        logger.debug("Question state reset.")

    async def generate_and_post_new_question(self):
        """Generates a new question using OpenAI and posts it to the quiz channel."""
        if not self.active_session_id:
            logger.warning("Cannot generate question: No active quiz session.")
            # channel = await self._get_quiz_channel()
            # if channel: await channel.send("An admin needs to start a quiz session with `/resetscores` before questions can be asked.")
            return

        self._reset_question_state() # Prepare for new question

        try:
            topics = self._load_topics()
            if not topics:
                logger.error("No topics found in topics.txt. Cannot generate question.")
                channel = await self._get_quiz_channel()
                if channel: await channel.send("Error: Could not load topics for the quiz. Admin check `topics.txt`.")
                return

            topic = random.choice(topics)
            difficulty_levels = ["basic knowledge", "intermediate knowledge", "advanced knowledge"]
            difficulty_choice = random.choice(difficulty_levels)

            logger.info(f"Requesting OpenAI for a '{difficulty_choice}' question on topic: '{topic}'")
            q_data = await self.openai_client.generate_question(topic, difficulty_choice)

            if not q_data or "error" in q_data:
                error_msg = q_data.get("error", "Unknown error from OpenAI") if q_data else "No data from OpenAI"
                logger.error(f"Failed to generate question from OpenAI: {error_msg}")
                channel = await self._get_quiz_channel()
                if channel: await channel.send(f"Oops! I had trouble thinking of a new question ({error_msg}). Trying again in a moment or an admin can use `/skipquestion`.")
                # Potentially add a retry mechanism here or rely on admin/timer skip
                return

            self.current_question_text = q_data["question"]
            self.current_question_intended_answer = q_data["intended_answer"]
            # Use AI's assessment of difficulty, or map our choice if AI doesn't return one
            self.current_question_difficulty = q_data.get("difficulty_assessment", difficulty_choice).lower() 

            if "basic" in self.current_question_difficulty:
                self.current_question_points = config.POINTS_EASY
            elif "intermediate" in self.current_question_difficulty:
                self.current_question_points = config.POINTS_MEDIUM
            elif "advanced" in self.current_question_difficulty:
                self.current_question_points = config.POINTS_DIFFICULT
            else: # Fallback
                self.current_question_points = config.POINTS_MEDIUM
                logger.warning(f"Unknown difficulty '{self.current_question_difficulty}', defaulting to medium points.")

            # Post the question
            channel = await self._get_quiz_channel()
            if channel:
                embed = discord.Embed(
                    title=f"🧠 New Quiz Question! ({self.current_question_points} Points)",
                    description=self.current_question_text,
                    color=discord.Color.blurple()
                )
                embed.add_field(name="Topic", value=topic.title(), inline=True)
                embed.add_field(name="Difficulty", value=self.current_question_difficulty.replace(" knowledge", "").title(), inline=True)
                embed.set_footer(text=f"Session #{self.active_session_id} | Use /answer <your answer>")
                
                question_msg = await channel.send(embed=embed)
                self.current_question_message_id = question_msg.id
                self.current_question_post_time = datetime.datetime.now(datetime.timezone.utc)
                self.user_attempts[self.current_question_message_id] = {} # Initialize attempts for this question
                logger.info(f"Posted new question (ID: {self.current_question_message_id}): {self.current_question_text}")
            else:
                logger.error("Cannot post question: Quiz channel not found.")

        except Exception as e:
            logger.error(f"Error in generate_and_post_new_question: {e}", exc_info=True)
            channel = await self._get_quiz_channel()
            if channel: await channel.send("A critical error occurred while trying to generate a new question. An admin has been notified (check logs).")

    def _load_topics(self):
        try:
            with open(config.TOPICS_FILE_PATH, "r", encoding="utf-8") as f:
                topics = [line.strip() for line in f if line.strip()]
            return topics
        except FileNotFoundError:
            logger.error(f"Topics file not found: {config.TOPICS_FILE_PATH}")
            return []

    async def process_user_answer(self, user: discord.User, answer_text: str) -> str:
        """Processes a user's answer, evaluates it, updates score, and provides feedback."""
        if not self.current_question_message_id or not self.active_session_id or self.question_answered_by:
            return "This question has already been answered or is no longer active."

        # Reset inactivity timer because an attempt was made
        self.current_question_post_time = datetime.datetime.now(datetime.timezone.utc) 

        question_attempts_key = self.current_question_message_id
        if question_attempts_key not in self.user_attempts: # Should not happen if initialized correctly
            self.user_attempts[question_attempts_key] = {}
            
        user_attempt_count = self.user_attempts[question_attempts_key].get(user.id, 0)

        if user_attempt_count >= config.MAX_ATTEMPTS_PER_QUESTION:
            return f"Sorry {user.mention}, you have used all your {config.MAX_ATTEMPTS_PER_QUESTION} attempts for this question."

        self.user_attempts[question_attempts_key][user.id] = user_attempt_count + 1
        attempts_remaining = config.MAX_ATTEMPTS_PER_QUESTION - (user_attempt_count + 1)

        logger.info(f"Evaluating answer from {user.id} for question {self.current_question_message_id}: '{answer_text}'")
        evaluation = await self.openai_client.evaluate_answer(
            self.current_question_text,
            self.current_question_intended_answer,
            answer_text
        )

        if not evaluation or "error" in evaluation:
            error_msg = evaluation.get("error", "Could not evaluate answer") if evaluation else "Could not evaluate answer"
            logger.error(f"OpenAI answer evaluation failed: {error_msg}")
            self.user_attempts[question_attempts_key][user.id] -= 1 # Revert attempt count
            return f"Sorry, I couldn't evaluate your answer right now due to an issue: {error_msg}. Please try again. Your attempt was not counted."

        status = evaluation.get("status", "Incorrect").lower()
        explanation = evaluation.get("explanation")
        
        db_manager = self.bot.db_manager
        if not db_manager:
             logger.error("DatabaseManager not available for score update.")
             return "Error: Could not connect to the database to update score."

        public_feedback = "" # Message to send to the main quiz channel
        private_feedback = "" # Message to send to the user ephemerally

        if status == "correct":
            points_awarded = self.current_question_points
            await db_manager.update_score(user.id, self.active_session_id, points_awarded)
            self.question_answered_by = user.id
            
            private_feedback = f"🎉 Correct, {user.mention}! You earned {points_awarded} points."
            public_feedback = f"🏆 {user.mention} answered correctly and earned {points_awarded} points! The answer was: **{self.current_question_intended_answer}**"
            logger.info(f"User {user.id} answered correctly. Awarded {points_awarded} points.")
            
        elif status == "partially correct":
            points_awarded = round(self.current_question_points / 2) # Half points
            await db_manager.update_score(user.id, self.active_session_id, points_awarded)
            self.question_answered_by = user.id

            private_feedback = f"👍 Partially Correct, {user.mention}! You earned {points_awarded} points. {explanation if explanation else ''}"
            public_feedback = (f"🤔 {user.mention} was partially correct and earned {points_awarded} points! "
                               f"{explanation if explanation else ''} The full intended answer was: **{self.current_question_intended_answer}**")
            logger.info(f"User {user.id} answered partially correct. Awarded {points_awarded} points.")

        else: # Incorrect
            points_deducted = config.POINTS_DEDUCTION_INCORRECT
            await db_manager.update_score(user.id, self.active_session_id, -points_deducted)
            
            private_feedback = (f"❌ Incorrect, {user.mention}. You lose {points_deducted} points. "
                                f"You have {attempts_remaining} attempts remaining for this question.")
            # No public feedback for incorrect answers to avoid spam, unless it's the last attempt or something.
            # For now, keep it private.
            logger.info(f"User {user.id} answered incorrectly. Deducted {points_deducted} points. Attempts remaining: {attempts_remaining}")
        
        # If question is now answered (correctly or partially)
        if self.question_answered_by:
            channel = await self._get_quiz_channel()
            if channel and public_feedback:
                original_question_embed = None
                try:
                    original_question_message = await channel.fetch_message(self.current_question_message_id)
                    if original_question_message and original_question_message.embeds:
                        original_question_embed = original_question_message.embeds[0]
                        original_question_embed.color = discord.Color.green() if status == "correct" else discord.Color.orange()
                        original_question_embed.set_footer(text=f"Answered by {user.display_name} | Session #{self.active_session_id}")
                        await original_question_message.edit(embed=original_question_embed, view=None) # Remove buttons if any
                except discord.NotFound:
                    logger.warning(f"Original question message {self.current_question_message_id} not found to update.")
                except Exception as e:
                    logger.error(f"Error updating original question message: {e}")

                await channel.send(public_feedback)
            
            # Schedule next question
            asyncio.create_task(self.generate_and_post_new_question()) # Don't await, let it run in background
            
        return private_feedback

    async def skip_current_question(self, admin_initiated=False, timeout_initiated=False) -> str:
        """Skips the current question, reveals answer, and prepares for the next."""
        if not self.current_question_message_id or not self.active_session_id:
            return "No active question to skip."

        reveal_message = f"The question was: \"{self.current_question_text}\"\nThe intended answer was: **{self.current_question_intended_answer}**."
        
        if admin_initiated:
            reason = "Skipped by an admin."
        elif timeout_initiated:
            reason = f"Question timed out after {config.QUESTION_INACTIVITY_TIMEOUT_HOURS} hours of inactivity. No one got it right."
        else: # Should not happen
            reason = "Question skipped."

        full_message = f"{reason} {reveal_message}"
        
        channel = await self._get_quiz_channel()
        if channel:
            try: # Try to edit the original question message to show it's skipped
                original_question_message = await channel.fetch_message(self.current_question_message_id)
                if original_question_message and original_question_message.embeds:
                    embed = original_question_message.embeds[0]
                    embed.color = discord.Color.dark_grey()
                    embed.description += f"\n\n**This question was skipped.**\nAnswer: {self.current_question_intended_answer}"
                    embed.set_footer(text=f"Skipped | Session #{self.active_session_id}")
                    await original_question_message.edit(embed=embed, view=None)
            except discord.NotFound:
                 logger.warning(f"Original question message {self.current_question_message_id} not found to update for skip.")
                 await channel.send(full_message) # Send as new message if original not found
            except Exception as e:
                logger.error(f"Error updating original question message on skip: {e}")
                await channel.send(full_message) # Fallback
        else:
            logger.error("Cannot announce skipped question: Quiz channel not found.")

        logger.info(f"Question {self.current_question_message_id} skipped. Reason: {reason.split('.')[0]}")
        self._reset_question_state() # Important: reset state for the next question
        # The calling function (admin command or timer) will trigger the next question generation.
        return full_message


    @tasks.loop(minutes=15) # Check every 15 minutes for inactivity
    async def question_inactivity_timer(self):
        await self.bot.wait_until_ready() # Ensure bot is connected and cogs are loaded

        if not self.active_session_id or not self.current_question_message_id or self.question_answered_by:
            # No active session, no current question, or question already answered
            return

        if self.current_question_post_time:
            now = datetime.datetime.now(datetime.timezone.utc)
            time_since_post_or_last_answer = now - self.current_question_post_time
            timeout_duration = datetime.timedelta(hours=config.QUESTION_INACTIVITY_TIMEOUT_HOURS)

            if time_since_post_or_last_answer > timeout_duration:
                logger.info(f"Question {self.current_question_message_id} timed out due to inactivity.")
                await self.skip_current_question(timeout_initiated=True)
                await self.generate_and_post_new_question() # Automatically post next one

    @question_inactivity_timer.before_loop
    async def before_question_inactivity_timer(self):
        await self.bot.wait_until_ready()
        logger.info("Question inactivity timer is waiting for the bot to be ready...")


async def setup(bot: commands.Bot):
    await bot.add_cog(GameManagerCog(bot))
    logger.info("GameManagerCog added to bot.")


