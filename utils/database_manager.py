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
                    last_exception = Exception(f"Supabase API error: {error_message}")
                    # If it's an error, continue to retry logic or raise if max attempts reached
                
                # If no error attribute or error is None, check for data
                elif hasattr(response, 'data'):
                    # Successful response with data
                    return response.data
                elif response is None: 
                    # Successful response that returns None (e.g., some updates/deletes might not return data)
                    return None
                else:
                    # If no error and no data, but also not None, it might be an unexpected structure
                    # However, some successful PATCH/POST operations return data as a list (like the one in logs)
                    # Let's assume if no error, and it's not None, it's a success.
                    # The previous log "Unexpected Supabase response structure" was for a successful PATCH.
                    # If 'data' is not the primary attribute for success, this might need adjustment
                    # based on how supabase-py structures responses for different operations.
                    # For now, if no error, consider it a success. The caller expects data or None.
                    # If response is the raw APIResponse object and has no .data but also no .error,
                    # it implies a success where no specific data body was expected by the client lib for that op.
                    logger.debug(f"Supabase call successful on attempt {attempt + 1}, response has no explicit .data or .error, returning raw response or None. Response: {type(response)}")
                    # If the operation was expected to return data, the calling function will handle it.
                    # For insert/update returning the new/updated row, it's in response.data.
                    # If an operation like delete is successful, it might not have .data.
                    return response # Or None if that's more appropriate for "no data content" success

                if last_exception and attempt == config.DB_MAX_RETRIES - 1: # If error occurred and it's the last attempt
                    raise last_exception

            except TypeError as te: 
                logger.error(f"TypeError during DB call on attempt {attempt + 1}: {te}. This indicates await might have been used on a non-awaitable.", exc_info=True)
                last_exception = te
            except Exception as e: 
                logger.warning(f"DB call failed on attempt {attempt + 1}/{config.DB_MAX_RETRIES}: {e}")
                last_exception = e
            
            if attempt == config.DB_MAX_RETRIES - 1:
                logger.error(f"DB call failed after {config.DB_MAX_RETRIES} attempts.")
                if last_exception:
                    raise last_exception
                else: 
                    raise Exception("DB call failed after max retries with no specific captured exception.")
            
            await asyncio.sleep(1 * (attempt + 1)) 
        return None 

    async def create_quiz_session(self) -> int | None:
        """Creates a new quiz session and returns its ID."""
        def _create_op_sync(): 
            return self.client.table("quiz_sessions").insert({}).execute()
        
        data = await self._db_call_with_retry(_create_op_sync) 
        if data and len(data) > 0: # Supabase insert returns a list with the new row
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
        
        # Update operations might return the updated rows in .data or just confirm success
        await self._db_call_with_retry(_end_op_sync)
        logger.info(f"Marked quiz session {session_id} as ended.")

    async def get_session_details(self, session_id: int) -> dict | None:
        """Retrieves details for a specific session."""
        def _get_op_sync():
            return self.client.table("quiz_sessions").select("*").eq("session_id", session_id).limit(1).execute()
        
        data = await self._db_call_with_retry(_get_op_sync)
        if data and len(data) > 0: # Select returns a list
            return data[0]
        return None

    async def update_score(self, user_id: str, session_id: int, points_change: int):
        """Updates a user's score for a given session. Creates the score entry if it doesn't exist."""
        user_id_str = str(user_id)
        
        def _update_op_sync():
            # This operation involves multiple steps; _db_call_with_retry might be better applied to individual execute calls
            # For now, keeping it as one "op_func"
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
            
            # Supabase update/insert typically returns a list of the affected rows in .data
            return final_response.data if hasattr(final_response, 'data') else None 

        # The data returned by _update_op_sync (which is final_response.data) is processed by _db_call_with_retry
        # If _db_call_with_retry gets this data, it will return it.
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
        
        data = await self._db_call_with_retry(_get_op_sync) # Select returns a list
        if data:
            return [(item['user_id'], item['score']) for item in data]
        return []
