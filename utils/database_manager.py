# utils/database_manager.py
import logging
from supabase import create_client, Client # Corrected import
import datetime
import asyncio # Added for asyncio.sleep
from config import config # For retry counts

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.client: Client | None = None # Type hint for sync client

    async def initialize(self): # Keep initialize async for setup_hook
        """Initializes the Supabase client and ensures tables exist."""
        if not self.supabase_url or not self.supabase_key:
            logger.error("Supabase URL or Key not provided. Database functions will fail.")
            raise ValueError("Supabase URL or Key missing.")
        
        try:
            # create_client is synchronous
            self.client = create_client(self.supabase_url, self.supabase_key)
            logger.info("Supabase client initialized successfully.")
            # _ensure_tables_exist can be called without await if it becomes fully synchronous
            # or keep it async if it might do other async things. For now, it's called with await.
            await self._ensure_tables_exist()
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}", exc_info=True)
            self.client = None 
            raise 

    async def _ensure_tables_exist(self):
        """
        Ensures that the required tables (quiz_sessions, scores) exist.
        This version treats execute() as synchronous based on TypeError observed.
        """
        if not self.client:
            logger.error("Supabase client not initialized. Cannot ensure tables.")
            return

        table_names = ["quiz_sessions", "scores"]
        select_fields = {"quiz_sessions": "session_id", "scores": "user_id"}

        for table_name in table_names:
            try:
                logger.debug(f"Verifying table: {table_name}")
                # Assuming execute() is behaving synchronously here based on the TypeError
                response = self.client.table(table_name).select(select_fields[table_name]).limit(1).execute()
                
                logger.info(f"Query for table '{table_name}' executed. Response type: {type(response)}")

                # Check response structure (APIResponse object from supabase-py)
                if hasattr(response, 'error') and response.error:
                     # This is where "relation does not exist" would be caught if HTTP 200 but SQL fails
                     logger.warning(f"Supabase API error while verifying '{table_name}': {response.error.message if hasattr(response.error, 'message') else response.error} (Code: {response.error.code if hasattr(response.error, 'code') else 'N/A'}). Please ensure it's created in Supabase.")
                elif hasattr(response, 'data'): 
                    logger.info(f"'{table_name}' table seems to exist and query was successful. Data: {response.data}")
                else:
                    # This case might indicate an issue if data is expected but not present,
                    # even without an explicit error object.
                    logger.warning(f"Unexpected response structure for '{table_name}' verification or no data returned: {response}")

            except TypeError as te: 
                # This specific catch is because the original error was a TypeError.
                # If execute() is now treated as sync, this TypeError should not occur from await.
                logger.error(f"TypeError during {table_name} check: {te}. This is unexpected if execute() is treated as synchronous.", exc_info=True)
            except Exception as e: # Catch other potential errors (network, etc.)
                logger.warning(f"Could not verify '{table_name}' table (may not exist or other issue): {e}. Please ensure it's created in Supabase.", exc_info=True)

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
        """
        Helper to retry database calls. Assumes 'coro' is an awaitable function
        that internally handles its Supabase calls (which might be sync or async
        depending on the specific Supabase client method).
        """
        if not self.client:
            logger.error("Supabase client not initialized. DB call aborted.")
            raise ConnectionError("Database client not initialized.")
        
        last_exception = None
        for attempt in range(config.DB_MAX_RETRIES):
            try:
                # The passed 'coro' is expected to be an async function that wraps
                # the actual Supabase client calls.
                response_data = await coro(*args, **kwargs) # This await is for the wrapper coro
                return response_data
            except Exception as e: 
                logger.warning(f"DB call failed on attempt {attempt + 1}/{config.DB_MAX_RETRIES}: {e}")
                last_exception = e
                if attempt == config.DB_MAX_RETRIES - 1:
                    logger.error(f"DB call failed after {config.DB_MAX_RETRIES} attempts.")
                    raise last_exception # Re-raise the last exception
            await asyncio.sleep(1 * (attempt + 1)) 
        return None 

    async def create_quiz_session(self) -> int | None:
        """Creates a new quiz session and returns its ID."""
        async def _create_op(): # This is the awaitable passed to _db_call_with_retry
            # Assuming self.client.table(...).execute() is async as per docs for actual operations
            response = await self.client.table("quiz_sessions").insert({}).execute()
            if hasattr(response, 'error') and response.error:
                raise Exception(f"Supabase API error creating session: {response.error.message}")
            if response.data and len(response.data) > 0:
                return response.data[0].get('session_id')
            return None
        
        session_id = await self._db_call_with_retry(_create_op)
        if session_id:
            logger.info(f"Created new quiz session with ID: {session_id}")
            return session_id
        logger.error("Failed to create quiz session or parse ID from response after retries.")
        return None

    async def end_quiz_session(self, session_id: int):
        """Marks a quiz session as ended."""
        async def _end_op():
            response = await self.client.table("quiz_sessions") \
                .update({"end_time": datetime.datetime.now(datetime.timezone.utc).isoformat()}) \
                .eq("session_id", session_id) \
                .execute()
            if hasattr(response, 'error') and response.error:
                raise Exception(f"Supabase API error ending session {session_id}: {response.error.message}")
            return response # Or some indicator of success

        await self._db_call_with_retry(_end_op)
        logger.info(f"Marked quiz session {session_id} as ended.")

    async def get_session_details(self, session_id: int) -> dict | None:
        """Retrieves details for a specific session."""
        async def _get_op():
            response = await self.client.table("quiz_sessions").select("*").eq("session_id", session_id).limit(1).execute()
            if hasattr(response, 'error') and response.error:
                raise Exception(f"Supabase API error getting session {session_id} details: {response.error.message}")
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        
        return await self._db_call_with_retry(_get_op)

    async def update_score(self, user_id: str, session_id: int, points_change: int):
        """Updates a user's score for a given session. Creates the score entry if it doesn't exist."""
        user_id_str = str(user_id)
        
        async def _update_op():
            existing_score_response = await self.client.table("scores") \
                .select("score") \
                .eq("user_id", user_id_str) \
                .eq("session_id", session_id) \
                .limit(1) \
                .execute()

            if hasattr(existing_score_response, 'error') and existing_score_response.error:
                raise Exception(f"DB error fetching score for {user_id_str}, session {session_id}: {existing_score_response.error.message}")

            final_response = None
            if existing_score_response.data: 
                current_score = existing_score_response.data[0]['score']
                new_score = current_score + points_change
                final_response = await self.client.table("scores") \
                    .update({"score": new_score}) \
                    .eq("user_id", user_id_str) \
                    .eq("session_id", session_id) \
                    .execute()
            else: 
                final_response = await self.client.table("scores") \
                    .insert({"user_id": user_id_str, "session_id": session_id, "score": points_change}) \
                    .execute()
            
            if hasattr(final_response, 'error') and final_response.error:
                raise Exception(f"DB error updating score for {user_id_str}, session {session_id}: {final_response.error.message}")
            return final_response # Or success indicator

        await self._db_call_with_retry(_update_op)
        logger.info(f"Updated score for user {user_id_str} in session {session_id} by {points_change} points.")


    async def get_leaderboard(self, session_id: int, limit: int = 10) -> list[tuple[str, int]]:
        """Retrieves the leaderboard for a given session."""
        async def _get_op():
            response = await self.client.table("scores") \
                .select("user_id, score") \
                .eq("session_id", session_id) \
                .order("score", desc=True) \
                .limit(limit) \
                .execute()
            if hasattr(response, 'error') and response.error:
                raise Exception(f"Supabase API error getting leaderboard for session {session_id}: {response.error.message}")
            if response.data:
                return [(item['user_id'], item['score']) for item in response.data]
            return []
        
        leaderboard_data = await self._db_call_with_retry(_get_op)
        return leaderboard_data if leaderboard_data is not None else []
