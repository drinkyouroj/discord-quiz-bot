# utils/openai_client.py
import openai # Using the official openai library v1.0.0+
import asyncio
import logging
import json # For parsing JSON responses
from config import config # For retry counts and API key

logger = logging.getLogger(__name__)

class OpenAIClient:
    def __init__(self, api_key: str):
        if not api_key:
            logger.error("OpenAI API key not provided. OpenAI functions will fail.")
            raise ValueError("OpenAI API key is missing.")
        try:
            # For openai library v1.0.0 and later, client is initialized like this:
            self.client = openai.AsyncOpenAI(api_key=api_key)
            logger.info("OpenAI AsyncClient initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
            raise

    async def _openai_call_with_retry(self, method_name, *args, **kwargs):
        """Helper to retry OpenAI API calls."""
        # Ensure 'model' is always provided if not already in kwargs
        if 'model' not in kwargs:
            kwargs['model'] = "gpt-3.5-turbo" # Default model, can be configured

        last_exception = None
        for attempt in range(config.OPENAI_MAX_RETRIES):
            try:
                method_to_call = getattr(self.client.chat.completions, method_name)
                response = await method_to_call(*args, **kwargs)
                return response
            except openai.APIConnectionError as e:
                logger.warning(f"OpenAI APIConnectionError on attempt {attempt + 1}: {e}")
                last_exception = e
            except openai.RateLimitError as e:
                logger.warning(f"OpenAI RateLimitError on attempt {attempt + 1}: {e}. Retrying after backoff...")
                last_exception = e
                await asyncio.sleep(5 * (attempt + 1)) # Longer backoff for rate limits
            except openai.APIStatusError as e:
                logger.error(f"OpenAI APIStatusError on attempt {attempt + 1}: status={e.status_code}, response={e.response}")
                last_exception = e
                # Do not retry for certain status codes like 400, 401, 403, 404
                if e.status_code in [400, 401, 403, 404, 429]: # Added 429 for safety, though RateLimitError should catch it
                    raise e # Re-raise immediately for these errors
            except Exception as e: # Catch any other OpenAI specific or general errors
                logger.error(f"Unexpected error during OpenAI call on attempt {attempt + 1}: {e}", exc_info=True)
                last_exception = e
            
            if attempt == config.OPENAI_MAX_RETRIES - 1:
                logger.error(f"OpenAI call failed after {config.OPENAI_MAX_RETRIES} attempts.")
                if last_exception:
                    raise last_exception
                else: # Should not happen if loop completed
                    raise Exception("OpenAI call failed after max retries with no specific exception.")
            
            # Simple exponential backoff
            sleep_time = (2 ** attempt) + random.uniform(0, 1) # Add jitter
            logger.info(f"Retrying OpenAI call in {sleep_time:.2f} seconds...")
            await asyncio.sleep(sleep_time)
        return None # Should ideally not be reached if exceptions are re-raised

    async def generate_question(self, topic: str, difficulty: str) -> dict | None:
        """
        Generates a quiz question using OpenAI.
        Difficulty: "basic knowledge", "intermediate knowledge", "advanced knowledge"
        Returns a dict: {"question": "...", "intended_answer": "...", "difficulty_assessment": "..."} or {"error": "..."}
        """
        prompt = f"""
        You are an AI that generates quiz questions for a Discord bot.
        The questions should have short, concise answers (a few words at most, ideally one or two).
        They can be fill-in-the-blank or conceptual questions.
        The topics are related to: Bitcoin, Web3, Decentralization, Blockchain.

        Generate a question on the topic: "{topic}"
        The desired difficulty level is: "{difficulty}" (e.g., basic knowledge, intermediate knowledge, advanced knowledge).

        Your response MUST be a JSON object with the following exact keys:
        - "question": A string containing the question.
        - "intended_answer": A string containing the concise, correct answer.
        - "difficulty_assessment": A string assessing the actual difficulty of the generated question (e.g., "basic knowledge", "intermediate", "advanced"). This can be your own assessment based on the question you generated.

        Example of a "basic knowledge" question about Bitcoin:
        {{
            "question": "What is the smallest unit of Bitcoin called?",
            "intended_answer": "satoshi",
            "difficulty_assessment": "basic knowledge"
        }}
        
        Example of an "intermediate knowledge" question about Web3:
        {{
            "question": "Which consensus mechanism is Ethereum transitioning to from Proof-of-Work?",
            "intended_answer": "Proof-of-Stake",
            "difficulty_assessment": "intermediate knowledge"
        }}

        Ensure the "intended_answer" is very specific and what you expect the user to type.
        Do not include any explanations or text outside the JSON object.
        The entire response should be ONLY the JSON object.
        """
        try:
            logger.debug(f"Sending prompt to OpenAI for question generation: Topic='{topic}', Difficulty='{difficulty}'")
            response = await self._openai_call_with_retry(
                "create",
                messages=[{"role": "user", "content": prompt}],
                model="gpt-3.5-turbo", # Explicitly state model
                temperature=0.7, 
                # For newer models that support JSON mode reliably:
                # response_format={"type": "json_object"} 
            )
            if response and response.choices:
                content = response.choices[0].message.content
                logger.debug(f"OpenAI raw response for question gen: {content}")
                
                # Attempt to parse the JSON content
                try:
                    # Clean potential markdown code block fences
                    if content.strip().startswith("```json"):
                        content_cleaned = content.strip()[7:-3].strip()
                    elif content.strip().startswith("```"):
                         content_cleaned = content.strip()[3:-3].strip()
                    else:
                        content_cleaned = content.strip()
                    
                    data = json.loads(content_cleaned)
                    if all(k in data for k in ["question", "intended_answer", "difficulty_assessment"]):
                        return data
                    else:
                        logger.error(f"OpenAI response missing required keys. Raw: {content}, Cleaned: {content_cleaned}")
                        return {"error": "OpenAI response missing required keys."}
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from OpenAI response. Raw: {content}. Error: {e}")
                    return {"error": f"Failed to parse JSON from OpenAI: {e}"}
            else:
                logger.error("No response or choices from OpenAI for question generation.")
                return {"error": "No response from OpenAI."}
        except Exception as e:
            logger.error(f"Error generating question with OpenAI: {e}", exc_info=True)
            return {"error": str(e)}

    async def evaluate_answer(self, question: str, intended_answer: str, user_answer: str) -> dict | None:
        """
        Evaluates a user's answer against the intended answer using OpenAI.
        Returns a dict: {"status": "Correct"|"Incorrect"|"Partially correct", "explanation": "..." (if partial)} or {"error": "..."}
        """
        prompt = f"""
        You are an AI evaluating a user's answer to a quiz question.
        The original question was: "{question}"
        The intended concise correct answer is: "{intended_answer}"
        The user's answer was: "{user_answer}"

        Analyze the user's answer. Determine if it is "Correct", "Incorrect", or "Partially correct".
        - "Correct" means the user's answer is essentially the same as the intended answer, allowing for minor variations in phrasing if the core concept is identical.
        - "Partially correct" means the user's answer captures some aspect of the correct answer but is incomplete, or contains correct information alongside incorrect information, or is a less precise but related correct concept.
        - "Incorrect" means the user's answer is wrong.

        Your response MUST be a JSON object with the following exact keys:
        - "status": A string, either "Correct", "Incorrect", or "Partially correct".
        - "explanation": A string. If the status is "Partially correct", provide a brief explanation of what makes it partial (e.g., "The user mentioned X, but a full answer also includes Y."). If "Correct" or "Incorrect", this can be null or a very brief confirmation (e.g., "User's answer is correct.").

        Example for a "Partially correct" evaluation:
        Question: "What are two common blockchain consensus mechanisms?"
        Intended Answer: "Proof-of-Work and Proof-of-Stake"
        User's Answer: "Proof of Work"
        JSON Response:
        {{
            "status": "Partially correct",
            "explanation": "The user mentioned Proof-of-Work, which is one correct mechanism, but missed Proof-of-Stake."
        }}
        
        Example for a "Correct" evaluation:
        Question: "Smallest unit of Bitcoin?"
        Intended Answer: "satoshi"
        User's Answer: "A satoshi"
        JSON Response:
        {{
            "status": "Correct",
            "explanation": "User's answer is correct."
        }}

        Do not include any text outside the JSON object.
        The entire response should be ONLY the JSON object.
        Be strict but fair. The "intended_answer" is the primary reference for correctness.
        """
        try:
            logger.debug(f"Sending prompt to OpenAI for answer evaluation. Q: '{question}', IA: '{intended_answer}', UA: '{user_answer}'")
            response = await self._openai_call_with_retry(
                "create",
                messages=[{"role": "user", "content": prompt}],
                model="gpt-3.5-turbo", # Explicitly state model
                temperature=0.2, 
                # response_format={"type": "json_object"} # For newer models
            )
            if response and response.choices:
                content = response.choices[0].message.content
                logger.debug(f"OpenAI raw response for answer eval: {content}")
                try:
                    if content.strip().startswith("```json"):
                        content_cleaned = content.strip()[7:-3].strip()
                    elif content.strip().startswith("```"):
                         content_cleaned = content.strip()[3:-3].strip()
                    else:
                        content_cleaned = content.strip()
                        
                    data = json.loads(content_cleaned)
                    if all(k in data for k in ["status", "explanation"]):
                        if data["status"] not in ["Correct", "Incorrect", "Partially correct"]:
                            logger.warning(f"OpenAI returned invalid status: {data['status']}. Defaulting to Incorrect. Raw: {content}")
                            data["status"] = "Incorrect" 
                        return data
                    else:
                        logger.error(f"OpenAI response missing required keys for eval. Raw: {content}, Cleaned: {content_cleaned}")
                        return {"error": "OpenAI eval response missing required keys."}
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from OpenAI eval response. Raw: {content}. Error: {e}")
                    return {"error": f"Failed to parse JSON from OpenAI eval: {e}"}
            else:
                logger.error("No response or choices from OpenAI for answer evaluation.")
                return {"error": "No response from OpenAI for eval."}
        except Exception as e:
            logger.error(f"Error evaluating answer with OpenAI: {e}", exc_info=True)
            return {"error": str(e)}
