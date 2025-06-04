# config.py
import os
from dotenv import load_dotenv
import logging # Import logging

logger = logging.getLogger(__name__) # Get a logger for this module

# Load environment variables from .env file
load_dotenv()

class Config:
    """
    Configuration class to hold settings loaded from environment variables
    or default values.
    """
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    
    ADMIN_USER_IDS_STR = os.getenv("ADMIN_USER_IDS", "")
    ADMIN_USER_IDS = [int(uid.strip()) for uid in ADMIN_USER_IDS_STR.split(',') if uid.strip().isdigit()] \
        if ADMIN_USER_IDS_STR else []

    QUIZ_CHANNEL_ID_STR = os.getenv("QUIZ_CHANNEL_ID")
    QUIZ_CHANNEL_ID = int(QUIZ_CHANNEL_ID_STR) if QUIZ_CHANNEL_ID_STR and QUIZ_CHANNEL_ID_STR.isdigit() else None

    # Default values for game mechanics
    QUESTION_INACTIVITY_TIMEOUT_HOURS = 2
    MAX_ATTEMPTS_PER_QUESTION = 5
    POINTS_EASY = 1
    POINTS_MEDIUM = 2
    POINTS_DIFFICULT = 5
    POINTS_DEDUCTION_INCORRECT = 2
    
    OPENAI_MAX_RETRIES = 10
    DB_MAX_RETRIES = 10

    TOPICS_FILE_PATH = "topics.txt"

    # Validate essential configuration
    if not DISCORD_BOT_TOKEN:
        # Use logger for critical errors if possible, or raise
        logger.critical("CRITICAL: DISCORD_BOT_TOKEN is not set in the environment variables.")
        raise ValueError("DISCORD_BOT_TOKEN is not set in the environment variables.")
    if not OPENAI_API_KEY:
        logger.critical("CRITICAL: OPENAI_API_KEY is not set in the environment variables.")
        raise ValueError("OPENAI_API_KEY is not set in the environment variables.")
    if not SUPABASE_URL:
        logger.critical("CRITICAL: SUPABASE_URL is not set in the environment variables.")
        raise ValueError("SUPABASE_URL is not set in the environment variables.")
    if not SUPABASE_KEY:
        logger.critical("CRITICAL: SUPABASE_KEY is not set in the environment variables.")
        raise ValueError("SUPABASE_KEY is not set in the environment variables.")
    
    if not QUIZ_CHANNEL_ID:
        # Changed from print to logger.warning
        logger.warning("Warning: QUIZ_CHANNEL_ID is not set or is invalid in .env. The bot might not be able to post questions to the designated channel.")
    
    if not ADMIN_USER_IDS:
        logger.warning("Warning: ADMIN_USER_IDS are not set in .env. Admin commands may not be usable as intended if they rely on this list.")


# Export an instance for easy import
config = Config()

