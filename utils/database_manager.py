# utils/database_manager.py
import logging
from supabase import create_client, Client # Using the async version
# from supabase import create_client, Client # For synchronous version if preferred
import datetime
from config import config # For retry counts

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.client: Client | None = None

    async def initialize(self):
        """Initializes the Supabase client and ensures tables exist."""
        if not self.supabase_url or not self.supabase_key:
            logger.error("Supabase URL or Key not provided. Database functions will fail.")
            raise ValueError("Supabase URL or Key missing.")
        
        try:
            self.client = create_client(self.supabase_url, self.supabase_key)
            logger.info("Supabase client initialized successfully.")
            await self._ensure_tables_exist()
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}", exc_info=True)
            self.client = None # Ensure client is None if init fails
            raise # Re-raise the exception to signal failure

    async def _ensure_tables_exist(self):
        """
        Ensures that the required tables (quiz_sessions, scores) exist.
        This is a simplified check; robust schema management might involve migration tools.
        For Supabase, you'd typically define these via the Supabase Studio UI or SQL.
        This function can serve as a basic check or a place to log if tables are missing.
        """
        if not self.client:
            logger.error("Supabase client not initialized. Cannot ensure tables.")
            return

        # Example: Check if 'quiz_sessions' table exists by trying to select from it.
        # This is a rudimentary check. Supabase's PostgREST API might not directly allow listing tables
        # without specific permissions or RPC functions.
        try:
            # Try a light query. If it fails due to missing table, it will raise an exception.
            await self.client.table("quiz_sessions").select("session_id").limit(1).execute()
            logger.info("'quiz_sessions' table seems to exist.")
        except Exception as e: # Catch a more specific exception if possible from supabase-py
            logger.warning(f"Could not verify 'quiz_sessions' table (may not exist or other issue): {e}. Please ensure it's created in Supabase.")
            # You might want to log instructions or raise a more critical error if tables are essential for startup.

        try:
            await self.client.table("scores").select("user_id").limit(1).execute()
            logger.info("'scores' table seems to exist.")
        except Exception as e:
            logger.warning(f"Could not verify 'scores' table (may not exist or other issue): {e}. Please ensure it's created in Supabase.")

        logger.info("Database table check complete. Refer to README.md for required schema.")
        # SQL for table creation (for reference, execute this in Supabase SQL Editor):
        #
        # CREATE TABLE IF NOT EXISTS quiz_sessions (
        #     session_id SERIAL PRIMARY KEY,
        #     start_time TIMESTAMPTZ DEFAULT now() NOT NULL,
        #     end_time TIMESTAMPTZ
        # );
        #
        # CREATE TABLE IF NOT EXISTS scores (
        #     user_id TEXT NOT NULL,
        #     session_id INTEGER NOT NULL,
        #     score INTEGER DEFAULT 0 NOT NULL,
        #     PRIMARY KEY (user_id, session_id),
        #     FOREIGN KEY (session_id) REFERENCES quiz_sessions(session_id) ON DELETE CASCADE
        # );
        # CREATE INDEX IF NOT EXISTS idx_scores_session_score ON scores(session_id, score DESC);


    async def _db_call_with_retry(self, coro, *args, **kwargs):
        """Helper to retry database calls."""
        if not self.client:
            logger.error("Supabase client not initialized. DB call aborted.")
            raise ConnectionError("Database client not initialized.") # Or return a specific error object
        
        for attempt in range(config.DB_MAX_RETRIES):
            try:
                response = await coro(*args, **kwargs)
                # supabase-py-async execute() returns a PostgrestAPIResponse object
                # Check for errors in the response if the library doesn't raise them directly
                # For example, response.error would contain an ApiError if one occurred.
                # However, common client errors or network issues might raise exceptions directly.
                if hasattr(response, 'error') and response.error:
                    logger.error(f"Supabase API error on attempt {attempt + 1}: {response.error.message}")
                    if attempt == config.DB_MAX_RETRIES - 1:
                        raise Exception(f"Supabase API error after multiple retries: {response.error.message}")
                    # You might want specific conditions for retrying, e.g., based on error codes
                elif hasattr(response, 'data') or response is None : # Some operations might return None on success
                    return response.data if hasattr(response, 'data') else None
                else: # Unexpected response structure
                    logger.error(f"Unexpected Supabase response structure on attempt {attempt + 1}: {response}")
                    if attempt == config.DB_MAX_RETRIES - 1:
                        raise Exception("Unexpected Supabase response structure after multiple retries.")
                
            except Exception as e: # Catch network errors, etc.
                logger.warning(f"DB call failed on attempt {attempt + 1}/{config.DB_MAX_RETRIES}: {e}")
                if attempt == config.DB_MAX_RETRIES - 1:
                    logger.error(f"DB call failed after {config.DB_MAX_RETRIES} attempts.")
                    raise # Re-raise the last exception
            await asyncio.sleep(1 * (attempt + 1)) # Exponential backoff (simple version)
        return None # Should not be reached if retries exhausted and exception raised

    async def create_quiz_session(self) -> int | None:
        """Creates a new quiz session and returns its ID."""
        async def _create():
            return await self.client.table("quiz_sessions").insert({}).execute()
        
        data = await self._db_call_with_retry(_create)
        if data and len(data) > 0:
            session_id = data[0].get('session_id')
            logger.info(f"Created new quiz session with ID: {session_id}")
            return session_id
        logger.error("Failed to create quiz session or parse ID from response.")
        return None

    async def end_quiz_session(self, session_id: int):
        """Marks a quiz session as ended."""
        async def _end():
            return await self.client.table("quiz_sessions") \
                .update({"end_time": datetime.datetime.now(datetime.timezone.utc).isoformat()}) \
                .eq("session_id", session_id) \
                .execute()
        
        await self._db_call_with_retry(_end)
        logger.info(f"Marked quiz session {session_id} as ended.")

    async def get_session_details(self, session_id: int) -> dict | None:
        """Retrieves details for a specific session."""
        async def _get():
            return await self.client.table("quiz_sessions").select("*").eq("session_id", session_id).limit(1).execute()
        
        data = await self._db_call_with_retry(_get)
        if data and len(data) > 0:
            return data[0]
        return None

    async def update_score(self, user_id: str, session_id: int, points_change: int):
        """Updates a user's score for a given session. Creates the score entry if it doesn't exist."""
        user_id_str = str(user_id) # Ensure user_id is string for DB
        
        async def _update():
            # Try to fetch existing score
            existing_score_response = await self.client.table("scores") \
                .select("score") \
                .eq("user_id", user_id_str) \
                .eq("session_id", session_id) \
                .limit(1) \
                .execute()

            if hasattr(existing_score_response, 'error') and existing_score_response.error:
                logger.error(f"Error fetching existing score for {user_id_str}, session {session_id}: {existing_score_response.error}")
                raise Exception(f"DB error fetching score: {existing_score_response.error.message}")

            if existing_score_response.data: # User has a score entry
                current_score = existing_score_response.data[0]['score']
                new_score = current_score + points_change
                return await self.client.table("scores") \
                    .update({"score": new_score}) \
                    .eq("user_id", user_id_str) \
                    .eq("session_id", session_id) \
                    .execute()
            else: # No score entry, create new one
                return await self.client.table("scores") \
                    .insert({"user_id": user_id_str, "session_id": session_id, "score": points_change}) \
                    .execute()

        await self._db_call_with_retry(_update)
        logger.info(f"Updated score for user {user_id_str} in session {session_id} by {points_change} points.")


    async def get_leaderboard(self, session_id: int, limit: int = 10) -> list[tuple[str, int]]:
        """Retrieves the leaderboard for a given session."""
        async def _get():
            return await self.client.table("scores") \
                .select("user_id, score") \
                .eq("session_id", session_id) \
                .order("score", desc=True) \
                .limit(limit) \
                .execute()
        
        data = await self._db_call_with_retry(_get)
        if data:
            return [(item['user_id'], item['score']) for item in data]
        return []


