from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os
import uuid
from dotenv import load_dotenv
from datetime import datetime
import json

# Custom JSON encoder to handle datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# Load environment variables from .env file
load_dotenv()

# Make sure agent modules are importable
# If running from workspace root, imports should work
# Otherwise, adjust PYTHONPATH if needed
from src.agent.agent import get_agent_for_pr, add_to_chat_history, get_chat_history

# Ensure OpenAI API key is set
if "OPENAI_API_KEY" not in os.environ:
    print("❌ OPENAI_API_KEY environment variable not set. Please check your .env file.")
else:
    print("✅ OPENAI_API_KEY loaded successfully (value hidden).")

app = FastAPI(
    title="Code Review AI Assistant",
    description="Backend API for the AI Code Review System",
    version="0.1.0",
)

class ChatRequest(BaseModel):
    query: str
    mode: str # "co_reviewer" or "interactive_assistant"
    pr_id: str
    participant_id: Optional[str] = None
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    timestamp: datetime = None
    mode: str  # Mode used for the response ("co_reviewer" or "interactive_assistant")
    pr_id: str  # PR ID associated with this response
    session_id: Optional[str] = None
    # chat_history: list # Optionally return history

# --- API Endpoint ---

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Handles chat requests, interacts with the agent, and returns the response."""
    
    print(f"Received request: {request.dict()}")
    
    # Check if session_id is None and generate a new one if needed
    session_id = request.session_id
    if session_id is None:
        session_id = str(uuid.uuid4())
        print(f"Created new session_id: {session_id}")

    # Logging configuration
    LOGGING_ENABLED = os.getenv("CHAT_LOGGING_ENABLED", "false").lower() in ("1","true","yes")
    LOG_DIR = os.getenv("CHAT_LOG_DIR", "logs")
    if LOGGING_ENABLED:
        os.makedirs(LOG_DIR, exist_ok=True)

    def persist_log(session_id: str, entry: dict):
        if not LOGGING_ENABLED:
            return
        log_path = os.path.join(LOG_DIR, f"{session_id}.log")
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, cls=DateTimeEncoder) + "\n")
    # Persist full request object
    request_data = request.dict()
    persist_log(session_id or "uninitialized", {"type": "request", **request_data})
    
    agent = get_agent_for_pr(request.pr_id, request.mode, session_id)
    
    if agent is None:
        print(f"Error: Failed to get or create agent for pr_id {request.pr_id} and session {session_id}")
        raise HTTPException(status_code=500, detail=f"Could not initialize agent for PR ID: {request.pr_id}. Check index availability and logs.")

    # Add user message to history *before* calling agent for context
    # (Though ReActAgent manages internal memory, explicit history can be useful)
    add_to_chat_history(session_id, {"role": "user", "content": request.query})

    response_text = ""
    try:
        # Refine the instruction prefix to emphasize following user instructions and providing thorough answers
        instruction_prefix = ("Follow the system prompts strictly, using tools for context when needed (do not use the start_review tool!). "
                             "Respond in English, format answers in Markdown, and use fenced code blocks with language tags for code snippets. "
                             "The following is the user's query; ensure you address it comprehensively and fulfill all instructions provided:\n\n")

        # Process the query directly, as the appropriate tool will be selected based on the query
        # The review_tool (start_review) will handle "start review" queries in co_reviewer mode
        if request.mode == "interactive_assistant" or request.mode == "co_reviewer":
            print(f"Mode: {request.mode} - Processing query: {request.query}")
            query = request.query
            if not request.query.startswith("start review"):
                query = instruction_prefix + request.query
            response = await agent.achat(query)
            response_text = str(response)
            print(f"Agent response: {response_text[:100]}...") # Log snippet
        else:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

        # Add assistant response to history
        add_to_chat_history(session_id, {"role": "assistant", "content": response_text})
        
        # Optional: Log full history for debugging
        # print(f"Chat History for session {session_id}: {get_chat_history(session_id)}")
        
        chat_response = ChatResponse(
            answer=response_text,
            timestamp=datetime.now(),
            mode=request.mode,
            pr_id=request.pr_id,
            session_id=session_id
        )
        # Persist full response object
        persist_log(session_id, {"type": "response", **chat_response.dict()})
        
        # Return the response
        return chat_response

    except Exception as e:
        print(f"Error during agent interaction for session {session_id} (PR: {request.pr_id}): {e}")
        # Add error indicator to history
        add_to_chat_history(session_id, {"role": "system", "content": f"Error processing request: {e}"})
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

# --- Root Endpoint (Optional) ---
@app.get("/")
async def root():
    return {"message": "Code Review AI Backend is running."}

# --- Run Instruction ---
if __name__ == "__main__":
    print("Starting FastAPI server...")
    print("Ensure OpenAI API key is set in your environment variables.")
    print("Run with: uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload")
    # Note: Running directly like this is for basic testing.
    # Uvicorn is the recommended way to run FastAPI apps.
    uvicorn.run(app, host="0.0.0.0", port=8000)
