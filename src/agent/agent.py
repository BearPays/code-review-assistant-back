import os
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv
import uuid

import chromadb
from llama_index.core import Settings, StorageContext, load_index_from_storage, VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core.agent import ReActAgent
from llama_index.core.tools import QueryEngineTool, ToolMetadata, FunctionTool
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core.response_synthesizers import get_response_synthesizer

from .prompts import SYSTEM_PROMPT_CO_REVIEWER, SYSTEM_PROMPT_INTERACTIVE_ASSISTANT
from .review_tool import create_review_tool
from .model_constants import OPENAI_LLM_MODEL, OPENAI_EMBEDDING_MODEL

# --- Settings ---
# Load environment variables from .env file
load_dotenv()

# Check if API key is available and print a message (without showing the key)
if "OPENAI_API_KEY" in os.environ:
    print("✅ OPENAI_API_KEY environment variable is set.")
else:
    print("❌ OPENAI_API_KEY environment variable is NOT set. Please check your .env file.")

Settings.llm = OpenAI(model=OPENAI_LLM_MODEL)
Settings.embed_model = OpenAIEmbedding(model=OPENAI_EMBEDDING_MODEL)

# --- Index Loading ---
def load_query_engine_tools(pr_id: str) -> List[QueryEngineTool]:
    """Loads query engines for the specified PR ID and returns them as tools.
    
    This loads indexed data from the ChromaDB collections created by scripts/index_data.py.
    The PR ID (e.g., 'project_1', 'project_2') corresponds to directory names under 'indexes/'.
    """
    
    index_dir = Path("indexes") / pr_id
    query_engine_tools = []
    
    if not index_dir.exists():
        print(f"Error: Project index directory not found: {index_dir}")
        return []  # Return empty list to signal failure
    
    # Collection/Storage mapping - adjust these mappings as needed
    tool_configs: List[Dict] = [
        {
            "storage_dir": "storage_pr_data",
            "name": "search_pr",
            "collection_name": f"{pr_id}_pr_data",
            "description": (
                "PRIMARY TOOL FOR CODE CHANGES: Use this tool for ANY questions about file diffs, changes, or modifications. "
                "This is THE ONLY tool that can answer questions about what was changed in the PR. "
                "The PR data is organized into multiple files: a main PR metadata file and individual files for each changed file in the PR. "
                "The metadata file contains information like 'pr_number', 'title', 'description', 'author', 'state', etc. "
                "Each modified file has its own JSON file in the 'modified_files' directory, preserving the original file path structure. "
                "For example, if a file at 'internal/integration/security_reentrant/oas_schemas_gen.go' was modified, "
                "its JSON file will be at 'modified_files/internal/integration/security_reentrant/oas_schemas_gen.go.json'. "
                "Each JSON file contains the 'filename', 'status', 'additions', 'deletions', and 'diff' information. "
                "In the root directory, there is a file called pr_metadata.json that contains information about the PR as a whole. Including a list of files that were changed as well as other metadata."
                "When using this tool for diffs, try queries like 'Show changes to file X' or 'Find diffs in the security module'. "
                "This is the FIRST tool to use for ANY query about what files were changed or how they were modified."
                "This is also the first tool to use when generating an initial code review. "
            ),
        },
        {
            "storage_dir": "storage_source_code", 
            "name": "search_code",
            "collection_name": f"{pr_id}_source_code",
            "description": (
                "INITIAL CODE STATE ONLY: This tool searches the initial state of the code before all changes. "
                "DO NOT use this tool for questions about changes, diffs, or what was modified - unless you want to compare the original code with the changes made in the PR. "
                "Use only for questions about implementation details, code structure, or how specific functionality works "
                "Use this tool to gain more context about the code and the specific changes by looking upp the complete codefiles, but be aware that it does not reflect any changes made in the PR."
            ),
        },
        {
            "storage_dir": "storage_pr_feature",
            "name": "search_requirements",
            "collection_name": f"{pr_id}_pr_feature", 
            "description": (
                "FEATURE REQUIREMENTS ONLY: Use this tool to search the feature requirements and specifications. "
                "This includes acceptance criteria, user stories, and what the PR is supposed to accomplish. "
                "Use this tool for example to compare the code changes with the feature requirements."
                "This tool can also be used to identify which changes are relevant to the feature being implemented in the PR."
                "Do not use this for code or PR change questions."
            ),
        },
    ]

    try:
        # Initialize ChromaDB client for this project
        print(f"Initializing ChromaDB client from: {index_dir}")
        chroma_client = chromadb.PersistentClient(path=str(index_dir))
    except Exception as e:
        print(f"Error initializing ChromaDB client for {pr_id}: {e}")
        return []
    
    for config in tool_configs:
        storage_path = index_dir / config["storage_dir"]
        
        try:
            # Get the ChromaDB collection
            collection = chroma_client.get_collection(config["collection_name"])
            print(f"Loaded ChromaDB collection: {config['collection_name']}")
            
            # Check if the collection has any items
            if collection.count() == 0:
                print(f"Warning: Collection {config['collection_name']} is empty. Creating a simple tool that reports this.")
                # Create a function that always returns a specific response about the collection being empty
                def empty_collection_func(input_text: str) -> str:
                    return f"The {config['name']} collection ({config['collection_name']}) is empty. No data is available for this tool."
                
                tool = FunctionTool.from_defaults(
                    name=config["name"],
                    description=config["description"],
                    fn=empty_collection_func
                )
            else:
                print(f"Collection {config['collection_name']} has {collection.count()} items.")
                # Create a vector store using the collection
                vector_store = ChromaVectorStore(chroma_collection=collection)
                
                # Create a storage context with the vector store and the storage directory
                storage_context = StorageContext.from_defaults(
                    vector_store=vector_store,
                    persist_dir=str(storage_path)
                )
                
                # Load the index from storage
                index = load_index_from_storage(storage_context)
                
                # Get appropriate parameters based on collection type
                similarity_top_k = 5  # Retrieve more results for better context
                
                # For PR data (JSON), adjust query parameters to better handle structured data, with a filter-capable query engine
                if "pr_data" in config["collection_name"]:
                    # Create a custom response synthesizer for PR data
                    response_synthesizer = get_response_synthesizer(
                        response_mode="refine",  # Use refine mode for structured data
                        verbose=True,
                    )
                    
                    # Create a query engine with custom parameters for PR data
                    query_engine = index.as_query_engine(
                        similarity_top_k=similarity_top_k,
                        response_synthesizer=response_synthesizer,
                        filters=None,  # We'll set this dynamically based on the query
                        verbose=True
                    )
                    print(f"Created PR-data specific query engine for {config['name']}")
                else:
                    # For code and requirements, use tree_summarize which works better for code/text
                    query_engine = index.as_query_engine(
                        similarity_top_k=similarity_top_k,
                        streaming=False,
                        response_mode="tree_summarize",
                        verbose=True
                    )
                
                print(f"Successfully created query engine for {config['name']}")
                
                # Create the tool
                tool = QueryEngineTool(
                    query_engine=query_engine,
                    metadata=ToolMetadata(
                        name=config["name"],
                        description=config["description"],
                    ),
                )
            
            query_engine_tools.append(tool)
            
        except Exception as e:
            print(f"Error loading tool {config['name']} for {pr_id}: {e}")
            continue
    
    if not query_engine_tools:
        print(f"Error: No query engine tools could be loaded for pr_id: {pr_id}")
    
    return query_engine_tools


# --- Agent Creation ---

def create_agent(pr_id: str, mode: str) -> ReActAgent:
    """Creates a ReActAgent for the given PR ID and interaction mode."""
    query_engine_tools = load_query_engine_tools(pr_id)

    # Check if any tools were loaded successfully
    if not query_engine_tools:
         print(f"Failed to create agent for pr_id {pr_id} as no tools were loaded.")
         return None

    # Add a debug tool that will help us see what's happening with the query engines
    def debug_tools(input_text: str) -> str:
        """Debug function to report on available tools and their raw collections."""
        response = f"Debug report for pr_id {pr_id}:\n"
        response += f"Number of tools available: {len(query_engine_tools)}\n"
        
        tool_names = [tool.metadata.name for tool in query_engine_tools]
        response += f"Tool names: {tool_names}\n"
        
        try:
            # Try to access the ChromaDB collections directly for debugging
            index_dir = Path("indexes") / pr_id
            client = chromadb.PersistentClient(path=str(index_dir))
            
            response += "\nCollection information:\n"
            for collection in client.list_collections():
                count = collection.count()
                response += f"- {collection.name}: {count} items\n"
                
                # If there are items, sample a few
                if count > 0:
                    try:
                        # Get a more substantial sample from PR data collection
                        if "pr_data" in collection.name and count > 0:
                            response += f"\n*** DETAILED PR DATA ANALYSIS ***\n"
                            sample = collection.get(limit=3)
                            
                            # Display document IDs and metadata
                            response += f"  Sample documents:\n"
                            for i, doc_id in enumerate(sample['ids']):
                                response += f"  Doc {i+1} ID: {doc_id}\n"
                                if sample['metadatas'][i]:
                                    response += f"  Metadata: {sample['metadatas'][i]}\n"
                                
                                # Show document text snippets (first 200 chars)
                                doc_text = sample['documents'][i]
                                if doc_text:
                                    snippet = doc_text[:300] + "..." if len(doc_text) > 300 else doc_text
                                    response += f"  Content snippet: {snippet}\n\n"
                            
                            # Try to identify fields related to file changes
                            response += "\n  Looking for file diff related fields in documents...\n"
                            change_related_terms = ["diff", "file", "change", "add", "remove", "modif", "patch"]
                            for term in change_related_terms:
                                for doc in sample['documents']:
                                    if term in doc.lower():
                                        context = doc[max(0, doc.lower().find(term) - 50):min(len(doc), doc.lower().find(term) + 150)]
                                        response += f"  Found '{term}' context: '...{context}...'\n"
                        else:
                            # Regular sample for other collections
                            sample = collection.get(limit=2)
                            response += f"  Sample metadata: {sample['metadatas']}\n"
                    except Exception as e:
                        response += f"  Error getting sample: {e}\n"
        except Exception as e:
            response += f"\nError accessing collections: {e}"
        
        return response

    debug_tool = FunctionTool.from_defaults(
        name="debug_info",
        description="Get debug information about the available tools and their data collections.",
        fn=debug_tools
    )

    # Add the debug tool to the list
    # query_engine_tools.append(debug_tool)
    
    # Add the review tool, but only in co_reviewer mode
    if mode == "co_reviewer":
        print(f"Adding review tool for co_reviewer mode")
        review_tool = create_review_tool(query_engine_tools, pr_id)
        query_engine_tools.append(review_tool)

    # Adjust system prompt based on mode
    if mode == "co_reviewer":
        system_prompt = SYSTEM_PROMPT_CO_REVIEWER
    elif mode == "interactive_assistant":
        system_prompt = SYSTEM_PROMPT_INTERACTIVE_ASSISTANT
    else:
        print(f"Error: Invalid mode {mode}")
        return None

    print(f"Creating ReActAgent with {len(query_engine_tools)} tools for {pr_id} in mode {mode}")
    agent = ReActAgent.from_tools(
        tools=query_engine_tools,
        llm=Settings.llm,
        system_prompt=system_prompt,
        max_iterations=10,
        verbose=True # Set to False in production
    )
    return agent

# --- Session Management ---
# Dictionaries to hold agent instances and chat history per session_id
# In a real app, use a more robust session management solution with persistence
agent_sessions: Dict[str, ReActAgent] = {} 
chat_history: Dict[str, List] = {} 

def get_agent_for_pr(pr_id: str, mode: str, session_id: str = None) -> ReActAgent:
    """
    Gets or creates an agent instance for a given session.
    
    Args:
        pr_id: The PR ID to load data for
        mode: The interaction mode ("co_reviewer" or "interactive_assistant")
        session_id: The unique session identifier (if None, pr_id will be used as fallback)
    
    Returns:
        ReActAgent instance or None if creation failed
    """
    # Use session_id if provided, otherwise fall back to pr_id for backward compatibility
    session_key = session_id if session_id else pr_id
    
    if session_key not in agent_sessions:
        print(f"Creating new agent for session: {session_key} (PR: {pr_id}, Mode: {mode})")
        agent_sessions[session_key] = create_agent(pr_id, mode)
        chat_history[session_key] = [] # Initialize chat history
    # Ensure agent creation was successful
    if agent_sessions.get(session_key) is None:
         # Handle the case where agent creation failed in create_agent
         print(f"Error: Agent for session {session_key} (PR: {pr_id}) could not be initialized.")
         # Returning None, the caller (e.g., FastAPI endpoint) must handle this
         return None
    return agent_sessions[session_key]

def get_chat_history(session_id: str) -> List:
     """
     Gets chat history for a given session ID.
     
     Args:
         session_id: The unique session identifier
         
     Returns:
         List of chat messages for the session or empty list if not found
     """
     return chat_history.get(session_id, [])

def add_to_chat_history(session_id: str, message):
     """
     Adds a message to the chat history.
     
     Args:
         session_id: The unique session identifier
         message: The message to add to the history
     """
     if session_id in chat_history:
         chat_history[session_id].append(message)

# --- Example Usage (Optional, for testing) ---
if __name__ == "__main__":
    # This block is for testing purposes only
    # Make sure OPENAI_API_KEY is set
    
    # Test with a specific PR ID that should have indexed data
    test_pr_id = "project_2"  # Replace with an actual PR ID from your indexed data
    test_mode = "co_reviewer"
    # Create a test session ID (simulating what would happen in the FastAPI endpoint)
    test_session_id = str(uuid.uuid4())
    
    print(f"\n--- Testing Agent with PR ID: {test_pr_id}, Mode: {test_mode}, Session ID: {test_session_id} ---")
    # Specify co_reviewer mode to test the review functionality
    test_agent = get_agent_for_pr(test_pr_id, test_mode, test_session_id)

    if test_agent:
        print("\n--- Testing Agent ---")
        
        # Test initial review for co-reviewer mode
        print("\n--- Testing Co-Reviewer Initial Summary ---")
        initial_review_query = "start review" 
        # In the real app, this is triggered internally, not by user query text
        response = test_agent.chat(initial_review_query) 
        print(f"Initial Review Response: {response}")
        add_to_chat_history(test_session_id, {"role": "assistant", "content": str(response)})

        # Test interactive query
        print("\n--- Testing Interactive Query ---")
        query = "What does the code do based on the requirements?"
        add_to_chat_history(test_session_id, {"role": "user", "content": query})
        response = test_agent.chat(query) 
        print(f"Query: {query}")
        print(f"Response: {response}")
        add_to_chat_history(test_session_id, {"role": "assistant", "content": str(response)})

        # Test follow-up query using history
        print("\n--- Testing Follow-up Query ---")
        follow_up_query = "Are there any potential issues?"
        add_to_chat_history(test_session_id, {"role": "user", "content": follow_up_query})
        response = test_agent.chat(follow_up_query) 
        print(f"Follow-up Query: {follow_up_query}")
        print(f"Response: {response}")
        add_to_chat_history(test_session_id, {"role": "assistant", "content": str(response)})
        
        print("\n--- Current Chat History ---")
        print(get_chat_history(test_session_id))

        # Test mode switching with same session ID (should reuse the same agent)
        print("\n--- Testing Mode Switching with Same Session ---")
        different_mode = "interactive_assistant"
        print(f"Switching mode to: {different_mode} (should reuse agent)")
        mode_switch_agent = get_agent_for_pr(test_pr_id, different_mode, test_session_id)
        print(f"Same agent instance? {mode_switch_agent is test_agent}")
        
        # Test PR switching with same session ID (should create a new agent)
        print("\n--- Testing Project Switching with Same Session ---")
        different_pr = "project_1"  # Assuming this project also exists
        print(f"Switching PR to: {different_pr}")
        different_pr_agent = get_agent_for_pr(different_pr, test_mode, test_session_id)
        print(f"Same agent instance? {different_pr_agent is test_agent}")
        
        # Test a completely new session (should create a new agent)
        print("\n--- Testing New Session ---")
        new_session_id = str(uuid.uuid4())
        print(f"Creating new session ID: {new_session_id}")
        new_session_agent = get_agent_for_pr(test_pr_id, test_mode, new_session_id)
        print(f"Same agent instance? {new_session_agent is test_agent}")
        
    else:
        print(f"Could not run test: Agent creation failed for pr_id {test_pr_id}, session {test_session_id}.")