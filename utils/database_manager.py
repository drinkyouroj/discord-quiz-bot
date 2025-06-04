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

                if hasattr(response, 'error') and response.error:
                     logger.warning(f"Supabase API error while verifying '{table_name}': {response.error.message if hasattr(response.error, 'message') else response.error} (Code: {response.error.code if hasattr(response.error, 'code') else 'N/A'}). Please ensure it's created in Supabase.")
                elif hasattr(response, 'data'): 
                    logger.info(f"'{table_name}' table seems to exist and query was successful. Data: {response.data}")
                else:
                    logger.warning(f"Unexpected response structure for '{table_name}' verification or no data returned: {response}")

            except TypeError as te: 
                logger.error(f"TypeError during {table_name} check: {te}. This is unexpected if execute() is treated as synchronous.", exc_info=True)
            except Exception as e: 
                logger.warning(f"Could not verify '{table_name}' table (may not exist or other issue): {e}. Please ensure it's created in Supabase.", exc_info=True)

        logger.info("Database table check complete. Refer to README.md for required schema.")

    async def _db_call_with_retry(self, op_func, *args, **kwargs):
        """
        Helper to retry database calls.
        'op_func' is a synchronous function that performs the Supabase client call.
        """
        if not self.client:
            logger.error("Supabase client not initialized. DB call aborted.")
            raise ConnectionError("Database client not initialized.")
        
        last_exception = None
        for attempt in range(config.DB_MAX_RETRIES):
            try:
                # op_func is called synchronously
                response = op_func(*args, **kwargs)
                
                # Check for errors in the response (common for Supabase client)
                if hasattr(response, 'error') and response.error:
                    error_message = response.error.message if hasattr(response.error, 'message') else str(response.error)
                    logger.error(f"Supabase API error on attempt {attempt + 1}: {error_message}")
                    # You might want specific conditions for not retrying, e.g., auth errors
                    last_exception = Exception(f"Supabase API error: {error_message}")
                elif hasattr(response, 'data') or response is None: # Some operations might return None or just response obj on success
                    return response.data if hasattr(response, 'data') else None
                else: # Unexpected response structure
                    logger.error(f"Unexpected Supabase response structure on attempt {attempt + 1}: {response}")
                    last_exception = Exception("Unexpected Supabase response structure.")

                if last_exception and attempt == config.DB_MAX_RETRIES - 1: # If error occurred and it's the last attempt
                    raise last_exception

                if not (hasattr(response, 'error') and response.error): # If no error, return data
                    return response.data if hasattr(response, 'data') else None


            except TypeError as te: # Catch the specific TypeError if await was misused
                logger.error(f"TypeError during DB call on attempt {attempt + 1}: {te}. This indicates await might have been used on a non-awaitable.", exc_info=True)
                last_exception = te
            except Exception as e: 
                logger.warning(f"DB call failed on attempt {attempt + 1}/{config.DB_MAX_RETRIES}: {e}")
                last_exception = e
            
            if attempt == config.DB_MAX_RETRIES - 1:
                logger.error(f"DB call failed after {config.DB_MAX_RETRIES} attempts.")
                if last_exception:
                    raise last_exception
                else: # Should not happen if loop completed without success or specific error
                    raise Exception("DB call failed after max retries with no specific captured exception.")
            
            await asyncio.sleep(1 * (attempt + 1)) 
        return None 

    async def create_quiz_session(self) -> int | None:
        """Creates a new quiz session and returns its ID."""
        def _create_op_sync(): 
            # This is now a synchronous call
            return self.client.table("quiz_sessions").insert({}).execute()
        
        data = await self._db_call_with_retry(_create_op_sync) # _db_call_with_retry handles async sleep/retry
        if data and len(data) > 0:
            session_id = data[0].get('session_id')
            logger.info(f"Created new quiz session with ID: {session_id}")
            return session_id
        logger.error("Failed to create quiz session or parse ID from response after retries.")
        return None

    async def end_quiz_session(self, session_id: int):
        """Marks a quiz session as ended."""
        def _end_op_sync():
            return self.client.table("quiz_sessions") \
                .update({"end_time": datetime.datetime.now(datetime.timezone.utc).isoformat()}) \
                .eq("session_id", session_id) \
                .execute()
        
        await self._db_call_with_retry(_end_op_sync)
        logger.info(f"Marked quiz session {session_id} as ended.")

    async def get_session_details(self, session_id: int) -> dict | None:
        """Retrieves details for a specific session."""
        def _get_op_sync():
            return self.client.table("quiz_sessions").select("*").eq("session_id", session_id).limit(1).execute()
        
        data = await self._db_call_with_retry(_get_op_sync)
        if data and len(data) > 0:
            return data[0]
        return None

    async def update_score(self, user_id: str, session_id: int, points_change: int):
        """Updates a user's score for a given session. Creates the score entry if it doesn't exist."""
        user_id_str = str(user_id)
        
        def _update_op_sync():
            existing_score_response = self.client.table("scores") \
                .select("score") \
                .eq("user_id", user_id_str) \
                .eq("session_id", session_id) \
                .limit(1) \
                .execute()

            if hasattr(existing_score_response, 'error') and existing_score_response.error:
                raise Exception(f"DB error fetching score for {user_id_str}, session {session_id}: {existing_score_response.error.message if hasattr(existing_score_response.error, 'message') else existing_score_response.error}")

            final_response = None
            if existing_score_response.data: 
                current_score = existing_score_response.data[0]['score']
                new_score = current_score + points_change
                final_response = self.client.table("scores") \
                    .update({"score": new_score}) \
                    .eq("user_id", user_id_str) \
                    .eq("session_id", session_id) \
                    .execute()
            else: 
                final_response = self.client.table("scores") \
                    .insert({"user_id": user_id_str, "session_id": session_id, "score": points_change}) \
                    .execute()
            
            if hasattr(final_response, 'error') and final_response.error:
                raise Exception(f"DB error updating score for {user_id_str}, session {session_id}: {final_response.error.message if hasattr(final_response.error, 'message') else final_response.error}")
            return final_response.data if hasattr(final_response, 'data') else None # Return data or None

        await self._db_call_with_retry(_update_op_sync)
        logger.info(f"Updated score for user {user_id_str} in session {session_id} by {points_change} points.")


    async def get_leaderboard(self, session_id: int, limit: int = 10) -> list[tuple[str, int]]:
        """Retrieves the leaderboard for a given session."""
        def _get_op_sync():
            return self.client.table("scores") \
                .select("user_id, score") \
                .eq("session_id", session_id) \
                .order("score", desc=True) \
                .limit(limit) \
                .execute()
        
        data = await self._db_call_with_retry(_get_op_sync)
        if data:
            return [(item['user_id'], item['score']) for item in data]
        return []
