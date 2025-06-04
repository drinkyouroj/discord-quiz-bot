# cogs/game_manager_cog.py
import discord
from discord.ext import commands, tasks
import asyncio
import random
import logging
import datetime 

from config import config 
from utils.openai_client import OpenAIClient

logger = logging.getLogger(__name__) # Get a logger for this cog

class GameManagerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GameManagerCog __init__: Initializing OpenAIClient...")
        try:
            self.openai_client = OpenAIClient(api_key=config.OPENAI_API_KEY)
            logger.info("GameManagerCog __init__: OpenAIClient initialized.")
        except Exception as e:
            logger.error("GameManagerCog __init__: Failed to initialize OpenAIClient.", exc_info=True)
            raise # Critical failure if OpenAI client can't init

        self.active_session_id = None
        
        self.current_question_text = None
        self.current_question_intended_answer = None
        self.current_question_difficulty = None 
        self.current_question_points = 0
        self.current_question_message_id = None 
        self.current_question_post_time = None 
        
        self.user_attempts = {} 
        self.question_answered_by = None 

        self.quiz_channel = None 

        logger.info("GameManagerCog __init__: Attempting to start question_inactivity_timer...")
        try:
            self.question_inactivity_timer.start()
            logger.info("GameManagerCog __init__: question_inactivity_timer started.")
        except Exception as e:
            logger.error("GameManagerCog __init__: Failed to start question_inactivity_timer.", exc_info=True)
            # Decide if this is critical enough to raise
        logger.info("GameManagerCog __init__ complete.")

    async def cog_load(self):
        logger.info("GameManagerCog cog_load method called.")
        if config.QUIZ_CHANNEL_ID:
            logger.debug(f"GameManagerCog cog_load: Waiting for bot to be ready to fetch channel {config.QUIZ_CHANNEL_ID}...")
            await self.bot.wait_until_ready() 
            self.quiz_channel = self.bot.get_channel(config.QUIZ_CHANNEL_ID)
            if not self.quiz_channel:
                logger.error(f"GameManagerCog cog_load: Could not find QUIZ_CHANNEL_ID: {config.QUIZ_CHANNEL_ID}.")
            else:
                logger.info(f"GameManagerCog cog_load: Quiz channel set to: {self.quiz_channel.name} (ID: {self.quiz_channel.id})")
        else:
            logger.warning("GameManagerCog cog_load: QUIZ_CHANNEL_ID not set. Bot cannot post questions.")
            
    def cog_unload(self):
        logger.info("GameManagerCog cog_unload: Cancelling question_inactivity_timer...")
        try:
            self.question_inactivity_timer.cancel()
            logger.info("GameManagerCog cog_unload: question_inactivity_timer cancelled.")
        except Exception as e:
            logger.error("GameManagerCog cog_unload: Error cancelling question_inactivity_timer.", exc_info=True)

    async def _get_quiz_channel(self) -> discord.TextChannel | None:
        """Ensures the quiz channel is available, re-fetching if necessary."""
        if not self.quiz_channel: # If not set during cog_load or became None
            if config.QUIZ_CHANNEL_ID:
                logger.debug("_get_quiz_channel: quiz_channel is None, attempting to fetch.")
                self.quiz_channel = self.bot.get_channel(config.QUIZ_CHANNEL_ID)
                if not self.quiz_channel:
                    logger.error(f"_get_quiz_channel: Re-fetch failed for QUIZ_CHANNEL_ID: {config.QUIZ_CHANNEL_ID}.")
            else:
                logger.warning("_get_quiz_channel: QUIZ_CHANNEL_ID not configured.")
        
        if not self.quiz_channel:
             logger.warning("_get_quiz_channel: Quiz channel is not available.")
        return self.quiz_channel

    async def start_new_quiz_session(self) -> str:
        logger.info("start_new_quiz_session called.")
        db_manager = getattr(self.bot, 'db_manager', None)
        if not db_manager:
            logger.error("start_new_quiz_session: DatabaseManager not found on bot instance.")
            raise ConnectionError("DatabaseManager not available.")

        if self.active_session_id:
            await db_manager.end_quiz_session(self.active_session_id)
            logger.info(f"Ended quiz session: {self.active_session_id}")
        
        self.active_session_id = await db_manager.create_quiz_session()
        if not self.active_session_id:
            logger.error("start_new_quiz_session: Failed to create a new session ID from DB.")
            return "Error: Could not start a new quiz session (DB issue)."
            
        logger.info(f"Started new quiz session: {self.active_session_id}")
        
        self._reset_question_state()
        
        session_details = await db_manager.get_session_details(self.active_session_id)
        start_time_str = "N/A"
        if session_details and session_details.get('start_time'):
            # Ensure start_time is datetime object before strftime
            st = session_details['start_time']
            if isinstance(st, str): # If Supabase returns ISO string
                try: # Attempt to parse ISO 8601 format
                    st_parsed = datetime.datetime.fromisoformat(st.replace('Z', '+00:00'))
                    st = st_parsed.astimezone(datetime.timezone.utc) # Ensure it's UTC
                except ValueError:
                     logger.error(f"Could not parse start_time string from DB: {st}")
                     st = None # Fallback
            
            if hasattr(st, 'strftime'): # Check if it's a datetime object
                 start_time_str = st.strftime('%Y-%m-%d %H:%M UTC')
            else:
                 logger.warning(f"Session start_time is not a recognizable datetime object: {st}")


        return f"New quiz session #{self.active_session_id} has started at {start_time_str}!"

    def _reset_question_state(self, clear_message_id=True):
        self.current_question_text = None
        self.current_question_intended_answer = None
        self.current_question_difficulty = None
        self.current_question_points = 0
        if clear_message_id:
             self.current_question_message_id = None
        self.current_question_post_time = None
        self.user_attempts.clear() 
        self.question_answered_by = None
        logger.debug("_reset_question_state: Question state has been reset.")

    async def generate_and_post_new_question(self):
        logger.info("generate_and_post_new_question called.")
        if not self.active_session_id:
            logger.warning("generate_and_post_new_question: No active quiz session.")
            channel = await self._get_quiz_channel()
            if channel:
                try:
                    await channel.send("An admin needs to start a quiz session with `/resetscores` before questions can be asked.")
                except discord.Forbidden:
                    logger.error(f"generate_and_post_new_question: Missing permissions to send message in channel {channel.id}")
                except Exception as e:
                    logger.error(f"generate_and_post_new_question: Error sending no-active-session message: {e}", exc_info=True)
            return

        self._reset_question_state() 

        try:
            topics = self._load_topics()
            if not topics:
                logger.error("generate_and_post_new_question: No topics found.")
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
                return

            self.current_question_text = q_data["question"]
            self.current_question_intended_answer = q_data["intended_answer"]
            self.current_question_difficulty = q_data.get("difficulty_assessment", difficulty_choice).lower() 

            if "basic" in self.current_question_difficulty: self.current_question_points = config.POINTS_EASY
            elif "intermediate" in self.current_question_difficulty: self.current_question_points = config.POINTS_MEDIUM
            elif "advanced" in self.current_question_difficulty: self.current_question_points = config.POINTS_DIFFICULT
            else: 
                self.current_question_points = config.POINTS_MEDIUM # Fallback
                logger.warning(f"Unknown difficulty '{self.current_question_difficulty}' from OpenAI, defaulting to medium points.")


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
                # Ensure user_attempts is a dict for the current question message ID
                if not isinstance(self.user_attempts, dict): self.user_attempts = {}
                self.user_attempts[self.current_question_message_id] = {} 
                logger.info(f"Posted new question (Msg ID: {self.current_question_message_id}): {self.current_question_text}")
            else:
                logger.error("generate_and_post_new_question: Cannot post question, quiz channel not found.")

        except Exception as e:
            logger.error(f"Error in generate_and_post_new_question: {e}", exc_info=True)
            channel = await self._get_quiz_channel()
            if channel: await channel.send("A critical error occurred while trying to generate a new question.")

    def _load_topics(self):
        try:
            with open(config.TOPICS_FILE_PATH, "r", encoding="utf-8") as f:
                topics = [line.strip() for line in f if line.strip()]
            if not topics: logger.warning(f"No topics loaded from {config.TOPICS_FILE_PATH}. File might be empty or all lines are blank.")
            return topics
        except FileNotFoundError:
            logger.error(f"Topics file not found: {config.TOPICS_FILE_PATH}")
            return []
        except Exception as e:
            logger.error(f"Error loading topics from {config.TOPICS_FILE_PATH}: {e}", exc_info=True)
            return []


    async def process_user_answer(self, user: discord.User, answer_text: str) -> str:
        logger.info(f"process_user_answer called for user {user.id}, answer: '{answer_text}'")
        if not self.current_question_message_id or not self.active_session_id:
            logger.warning(f"process_user_answer: No active question/session. Current msg_id: {self.current_question_message_id}, session_id: {self.active_session_id}")
            return "There's no active question or session right now."
        if self.question_answered_by:
            logger.info(f"process_user_answer: Question {self.current_question_message_id} already answered by {self.question_answered_by}.")
            # Fetch the user who answered to mention them
            answered_user = self.bot.get_user(self.question_answered_by) or await self.bot.fetch_user(self.question_answered_by)
            answered_user_mention = answered_user.mention if answered_user else f"User ID {self.question_answered_by}"
            return f"This question was already answered by {answered_user_mention}."

        self.current_question_post_time = datetime.datetime.now(datetime.timezone.utc) 

        question_attempts_key = self.current_question_message_id 
        if not isinstance(self.user_attempts, dict) or question_attempts_key not in self.user_attempts: 
            logger.warning(f"user_attempts not properly initialized for question {question_attempts_key}. Resetting.")
            if not isinstance(self.user_attempts, dict): self.user_attempts = {}
            self.user_attempts[question_attempts_key] = {} 
            
        user_attempt_count = self.user_attempts[question_attempts_key].get(user.id, 0)

        if user_attempt_count >= config.MAX_ATTEMPTS_PER_QUESTION:
            return f"Sorry {user.mention}, you have used all {config.MAX_ATTEMPTS_PER_QUESTION} attempts for this question."

        self.user_attempts[question_attempts_key][user.id] = user_attempt_count + 1
        attempts_remaining = config.MAX_ATTEMPTS_PER_QUESTION - self.user_attempts[question_attempts_key][user.id]

        logger.info(f"Evaluating answer from {user.id} for question {self.current_question_message_id}: '{answer_text}'")
        evaluation = await self.openai_client.evaluate_answer(
            self.current_question_text,
            self.current_question_intended_answer,
            answer_text
        )

        if not evaluation or "error" in evaluation:
            error_msg = evaluation.get("error", "Could not evaluate answer") if evaluation else "Could not evaluate answer"
            logger.error(f"OpenAI answer evaluation failed: {error_msg}")
            self.user_attempts[question_attempts_key][user.id] -= 1 
            return f"Sorry, I couldn't evaluate your answer right now: ({error_msg}). Your attempt was not counted. Please try again."

        status = evaluation.get("status", "Incorrect").lower()
        explanation = evaluation.get("explanation")
        
        db_manager = getattr(self.bot, 'db_manager', None)
        if not db_manager:
             logger.error("process_user_answer: DatabaseManager not available for score update.")
             return "Error: Could not connect to the database to update score."

        public_feedback_parts = []
        private_feedback = ""

        if status == "correct":
            points_awarded = self.current_question_points
            await db_manager.update_score(str(user.id), self.active_session_id, points_awarded)
            self.question_answered_by = user.id
            private_feedback = f"🎉 Correct, {user.mention}! You earned {points_awarded} points."
            public_feedback_parts.append(f"🏆 {user.mention} answered correctly and earned {points_awarded} points!")
            public_feedback_parts.append(f"The answer was: **{self.current_question_intended_answer}**")
            logger.info(f"User {user.id} answered correctly. Awarded {points_awarded} points.")
            
        elif status == "partially correct":
            points_awarded = round(self.current_question_points / 2) 
            await db_manager.update_score(str(user.id), self.active_session_id, points_awarded)
            self.question_answered_by = user.id
            private_feedback = f"👍 Partially Correct, {user.mention}! You earned {points_awarded} points. {explanation if explanation else ''}"
            public_feedback_parts.append(f"🤔 {user.mention} was partially correct and earned {points_awarded} points!")
            if explanation: public_feedback_parts.append(explanation)
            public_feedback_parts.append(f"The full intended answer was: **{self.current_question_intended_answer}**")
            logger.info(f"User {user.id} answered partially correct. Awarded {points_awarded} points.")

        else: # Incorrect
            points_deducted = config.POINTS_DEDUCTION_INCORRECT
            await db_manager.update_score(str(user.id), self.active_session_id, -points_deducted)
            private_feedback = (f"❌ Incorrect, {user.mention}. You lose {points_deducted} points. "
                                f"You have {attempts_remaining} attempts remaining for this question.")
            logger.info(f"User {user.id} answered incorrectly. Deducted {points_deducted} points. Attempts remaining: {attempts_remaining}")
        
        if self.question_answered_by:
            channel = await self._get_quiz_channel()
            if channel and public_feedback_parts:
                final_public_message = "\n".join(public_feedback_parts)
                try:
                    original_question_message = await channel.fetch_message(self.current_question_message_id)
                    if original_question_message and original_question_message.embeds:
                        original_embed = original_question_message.embeds[0].copy()
                        original_embed.color = discord.Color.green() if status == "correct" else discord.Color.orange()
                        original_embed.set_footer(text=f"Answered by {user.display_name} | Session #{self.active_session_id}")
                        
                        # Add answer to description or new field
                        # To avoid making the embed too long, we'll just update the footer and color.
                        # The public_feedback_parts will be sent as a new message.
                        
                        await original_question_message.edit(embed=original_embed, view=None) 
                        await channel.send(final_public_message) # Send separate message for answer details
                    else: 
                        await channel.send(final_public_message)
                except discord.NotFound:
                    logger.warning(f"Original question message {self.current_question_message_id} not found to update.")
                    await channel.send(final_public_message) 
                except Exception as e:
                    logger.error(f"Error updating original question message or sending public feedback: {e}", exc_info=True)
                    await channel.send(final_public_message) 
            
            logger.info(f"Question {self.current_question_message_id} resolved. Scheduling next question.")
            asyncio.create_task(self.generate_and_post_new_question()) 
            
        return private_feedback

    async def skip_current_question(self, admin_initiated=False, timeout_initiated=False) -> str:
        logger.info(f"skip_current_question called. Admin: {admin_initiated}, Timeout: {timeout_initiated}")
        if not self.current_question_message_id or not self.active_session_id:
            logger.warning("skip_current_question: No active question/session to skip.")
            return "No active question to skip."
        
        # Store details before resetting state
        skipped_question_text = self.current_question_text
        skipped_intended_answer = self.current_question_intended_answer
        skipped_message_id = self.current_question_message_id

        self._reset_question_state() # Reset state immediately so no new answers are processed for the old q
        
        reveal_message = f"The question was: \"{skipped_question_text}\"\nThe intended answer was: **{skipped_intended_answer}**."
        
        if admin_initiated: reason = "Skipped by an admin."
        elif timeout_initiated: reason = f"Question timed out after {config.QUESTION_INACTIVITY_TIMEOUT_HOURS} hours of inactivity. No one got it right."
        else: reason = "Question skipped."

        full_message_for_channel = f"{reason}\n{reveal_message}"
        
        channel = await self._get_quiz_channel()
        if channel:
            try: 
                original_question_message = await channel.fetch_message(skipped_message_id)
                if original_question_message and original_question_message.embeds:
                    embed = original_question_message.embeds[0].copy()
                    embed.color = discord.Color.dark_grey()
                    # Update embed description to show it's skipped and reveal answer
                    embed.description = (f"**This question was skipped.**\n\n"
                                         f"Original Question: {skipped_question_text}\n"
                                         f"Intended Answer: **{skipped_intended_answer}**")
                    embed.clear_fields() # Remove old topic/difficulty fields
                    embed.add_field(name="Status", value="Skipped", inline=True)
                    if self.active_session_id: # Check if active_session_id is still valid (it should be)
                        embed.set_footer(text=f"Skipped | Session #{self.active_session_id}")
                    else:
                        embed.set_footer(text="Skipped")
                    await original_question_message.edit(content=f"This question has been skipped. {reason}", embed=embed, view=None)
                else: 
                    await channel.send(full_message_for_channel)
            except discord.NotFound:
                 logger.warning(f"Original question message {skipped_message_id} not found to update for skip.")
                 await channel.send(full_message_for_channel) 
            except Exception as e:
                logger.error(f"Error updating original question message on skip: {e}", exc_info=True)
                await channel.send(full_message_for_channel) 
        else:
            logger.error("skip_current_question: Cannot announce skipped question, quiz channel not found.")

        logger.info(f"Question {skipped_message_id} skipped. Reason: {reason.split('.')[0]}")
        return f"Question skipped. {reveal_message}" 


    @tasks.loop(minutes=15) # Check every 15 minutes for inactivity
    async def question_inactivity_timer(self):
        await self.bot.wait_until_ready() 

        if not self.active_session_id or not self.current_question_message_id or self.question_answered_by:
            return 

        if self.current_question_post_time:
            now = datetime.datetime.now(datetime.timezone.utc)
            time_since_last_activity = now - self.current_question_post_time 
            timeout_duration = datetime.timedelta(hours=config.QUESTION_INACTIVITY_TIMEOUT_HOURS)

            if time_since_last_activity > timeout_duration:
                logger.info(f"Question {self.current_question_message_id} timed out due to inactivity (last activity at {self.current_question_post_time}).")
                await self.skip_current_question(timeout_initiated=True)
                await self.generate_and_post_new_question() 
        else:
            logger.debug("question_inactivity_timer: No current_question_post_time set, cannot check for timeout.")


    @question_inactivity_timer.before_loop
    async def before_question_inactivity_timer(self):
        logger.info("question_inactivity_timer: Waiting for bot to be ready before starting loop...")
        await self.bot.wait_until_ready()
        logger.info("question_inactivity_timer: Bot is ready. Loop will start.")


async def setup(bot: commands.Bot):
    logger.info("Attempting to setup GameManagerCog...")
    try:
        cog_instance = GameManagerCog(bot)
        await bot.add_cog(cog_instance)
        logger.info("GameManagerCog setup complete and cog added to bot.")
    except Exception as e:
        logger.error(f"Failed during GameManagerCog setup or add_cog: {e}", exc_info=True)
        raise 