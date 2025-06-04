# AI Quiz Discord Bot

## Overview

The AI Quiz Discord Bot runs an engaging, ongoing quiz directly in your Discord server. It features AI-generated questions from a variety of subjects, with AI-powered answer evaluation, allowing for free-form responses. Users earn points for correct answers, lose points for incorrect ones, and compete on a session-based leaderboard.

## Features

* **Continuous Quiz Sessions:** The quiz runs in sessions, initiated by an admin. Scores are tracked per session.
* **AI-Generated Questions:** Questions are generated on-the-fly by OpenAI's API based on a predefined list of subjects (e.g., bitcoin, web3, blockchain, decentralization).
* **Variable Difficulty & Points:**
    * Questions are requested at "basic," "intermediate," or "advanced" knowledge levels.
    * **Correct Answers:** Easy (1 pt), Medium (2 pts), Difficult (5 pts).
    * **Partially Correct Answers:** Easy (0.5 pts), Medium (1 pt), Difficult (2.5 pts).
    * **Incorrect Answers:** -2 points.
* **AI-Powered Free-Form Answer Evaluation:** User answers are evaluated by OpenAI for correctness against an intended answer, allowing for flexibility in phrasing.
* **Partial Credit with Explanations:** If an answer is "Partially correct," the AI provides an explanation for what was missing or incorrect.
* **Attempt Limits:** Each user gets 5 attempts per question.
* **Question Timer:** Each question has a 2-hour inactivity timer. If no user attempts an answer within this period, the question is skipped. The timer resets upon *any* answer submission for that question.
* **Persistent Leaderboards:** Scores are stored in a Supabase (PostgreSQL) database, tied to quiz sessions.
* **Admin Controls:** Admins can manage quiz sessions and skip questions.

## Core Technologies

* **Programming Language:** Python 3.x
* **Discord Library:** `discord.py`
* **AI Services:** OpenAI API (for question generation and answer evaluation)
* **Database:** Supabase (PostgreSQL)

## Key Functionality Details

### 1. Quiz Sessions
* A new quiz session is started using the `/resetscores` admin command.
* This command finalizes any previous session (if active) by marking its end time and initiates a new one.
* Scores and leaderboard displays are specific to the current active session. Historical session data is retained in the database.

### 2. Question Generation & Posting
* A topic is randomly selected from a `topics.txt` file.
* A difficulty level ("basic," "intermediate," "advanced") is randomly chosen.
* OpenAI is prompted to provide a question, its assessed difficulty, and the *intended concise answer*.
    * *Format Example:* `{"question": "...", "difficulty_assessment": "...", "intended_answer": "..."}`
* The question is posted to Discord with its mapped point value.
* A 2-hour inactivity timer begins.

### 3. Answering Mechanism
* Users submit answers using `/answer <your_answer>`.
* Answers are processed serially. The bot evaluates one answer at a time for the current question.
* The user's answer is sent to OpenAI along with the original question and the AI's `intended_answer` for evaluation.
    * *Expected AI Response:* `{"status": "Correct"|"Incorrect"|"Partially correct", "explanation": "..." (if partial)}`
* The 2-hour question inactivity timer resets with *every* answer attempt.

### 4. Scoring & Feedback
* **Correct:** Full points awarded. User congratulated.
* **Partially Correct:** Half points awarded. User congratulated, AI explanation and full intended answer provided.
* **Incorrect:** 2 points deducted. User informed of incorrect answer and remaining attempts.
* The first user to provide a "Correct" or "Partially correct" answer for a question secures the points. Subsequent attempts by other users on the same question are informed it has already been answered.
* User scores are updated in the Supabase database for the current session.

### 5. Question Timeout & Skipping
* **Timeout:** If 2 hours pass with no answer submissions for the current question, it is skipped. The `intended_answer` is revealed.
* **Admin Skip:** The `/skipquestion` command allows admins to skip the current question, revealing the `intended_answer`.
* A new question is generated after a question is skipped or timed out.

### 6. Leaderboard
* The `/leaderboard` command displays the top scores for the current quiz session, including the session ID and start time.
* If no session is active, it prompts an admin to start one.

## Commands

### Admin Commands
* `/resetscores`: Ends the current quiz session (if any) and starts a new one. Posts the first question of the new session.
* `/skipquestion`: Skips the current active question, reveals its intended answer, and posts a new question.

### User Commands
* `/answer <your_answer>`: Submits an answer to the current question.
* `/leaderboard`: Displays the leaderboard for the current quiz session.

## Setup & Configuration (High-Level)

1.  **Clone the repository.**
2.  **Create a virtual environment and install dependencies from `requirements.txt`.**
3.  **Set up `topics.txt`:** Populate this file with one quiz topic per line.
4.  **Configure Environment Variables (in a `.env` file):**
    * `DISCORD_BOT_TOKEN`: Your Discord bot token.
    * `OPENAI_API_KEY`: Your OpenAI API key.
    * `SUPABASE_URL`: Your Supabase project URL.
    * `SUPABASE_KEY`: Your Supabase project anon (public) key or service role key (if writes are restricted).
    * `LOG_LEVEL`: (Optional) e.g., INFO, DEBUG.
5.  **Database Schema:** Ensure your Supabase instance has the required tables:
    * `quiz_sessions (session_id SERIAL PRIMARY KEY, start_time TIMESTAMPTZ DEFAULT now(), end_time TIMESTAMPTZ)`
    * `scores (user_id TEXT, session_id INTEGER, score INTEGER, PRIMARY KEY (user_id, session_id), FOREIGN KEY (session_id) REFERENCES quiz_sessions(session_id) ON DELETE CASCADE)`
6.  **Run the bot:** `python bot.py`

## Error Handling

* The bot includes retry mechanisms for OpenAI API calls and Supabase database operations (up to 10 attempts with increasing backoff).
* Persistent errors are logged, and in some cases, an admin or a designated channel may be notified.
* If answer evaluation fails due to an API error, the user is informed, and their score/attempts are not affected for that try.
