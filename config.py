# config.py
import os
from dotenv import load_dotenv

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
    
    # Optional: Admin User IDs (comma-separated string, parsed into a list of ints)
    ADMIN_USER_IDS_STR = os.getenv("ADMIN_USER_IDS", "")
    ADMIN_USER_IDS = [int(uid.strip()) for uid in ADMIN_USER_IDS_STR.split(',') if uid.strip().isdigit()] \
        if ADMIN_USER_IDS_STR else []

    QUIZ_CHANNEL_ID_STR = os.getenv("QUIZ_CHANNEL_ID")
    QUIZ_CHANNEL_ID = int(QUIZ_CHANNEL_ID_STR) if QUIZ_CHANNEL_ID_STR and QUIZ_CHANNEL_ID_STR.isdigit() else None

    # Default values for game mechanics (can be overridden or made configurable later)
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
        raise ValueError("DISCORD_BOT_TOKEN is not set in the environment variables.")
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in the environment variables.")
    if not SUPABASE_URL:
        raise ValueError("SUPABASE_URL is not set in the environment variables.")
    if not SUPABASE_KEY:
        raise ValueError("SUPABASE_KEY is not set in the environment variables.")
    if not QUIZ_CHANNEL_ID:
        print("Warning: QUIZ_CHANNEL_ID is not set or is invalid. The bot might not know where to post questions.")


# Export an instance for easy import
config = Config()

