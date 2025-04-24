import os
from typing import List, Dict, Optional
from llama_index.core import Settings
from llama_index.core.agent import ReActAgent
from llama_index.core.tools import QueryEngineTool, FunctionTool, ToolMetadata
from llama_index.llms.openai import OpenAI

from .pr_data import get_pr_data

# Review-specific system prompt that focuses on instructions rather than data
REVIEW_SYSTEM_PROMPT = """
You are an expert code reviewer tasked with analyzing Pull Requests.

## YOUR ROLE AND PURPOSE
Your job is to perform a COMPREHENSIVE and DETAILED code review of a pull request.
You have access to tools that let you search the code base and requirements to gain more context.

## TOOL CALLING
You have tools at your disposal to help you conduct the review.
You can use the search_code tool to examine related code see the whole code file before changes, to infer code standards and convention in the codebase and to understand the codebase better
You can use the search_requirements tool to understand the feature requirements that the PR implements (if applicable)

## HOW TO CONDUCT THE REVIEW
1. First, understand the purpose of the PR by analyzing the PR title, description, and requirements (if applicable)
2. Use the search_code tool to examine related code see the whole code file before changes, to infer code standards and convention in the codebase and to understand the codebase better
3. Use the search_requirements tool to understand the feature requirements that the PR implements (if applicable)
4. Form a DETAILED analysis of each changed file, focusing on:
   - Code correctness and potential bugs
   - Architecture and design choices
   - Performance implications
   - Security concerns
   - Code readability and maintainability
   - Test coverage
   - Adherence to requirements

## REVIEW FORMAT
Your review MUST be organized into these sections:

### PR Summary
A concise overview of what the PR does and why, based on PR description and requirements.

### Overall Assessment
A high-level evaluation indicating whether the PR is ready to merge or needs changes.

### Detailed Analysis
For each file changed, provide:
1. **File:** [filename]
2. **Changes:** Summary of changes made to this file
3. **Feedback:**
   - List specific issues, concerns, or compliments with line references where applicable
   - Code snippets to illustrate points
   - Suggestions for improvement

### Security & Performance
Highlight any security or performance concerns

### Testing
Comment on test coverage and quality

### Documentation
Evaluate if documentation is sufficient

### Adherence to Requirements
How well the implementation meets requirements

## IMPORTANT GUIDELINES
- Be specific and detailed, not general
- Reference specific lines of code when giving feedback
- Provide actionable suggestions when identifying problems
- Always look for edge cases and potential bugs
- If you need more context about specific code parts, use the search_code tool
- If you need to check requirements, use the search_requirements tool
- Always answer in English
"""

def create_review_tool(tools: List[QueryEngineTool], pr_id: str) -> FunctionTool:
    """
    Creates a tool that generates a comprehensive code review for a PR.
    
    Args:
        tools: The list of query engine tools to pass to the sub-agent
        pr_id: The ID of the PR to review
        
    Returns:
        FunctionTool: A tool that can be triggered with "start review"
    """
    # Find and filter only the tools we want to pass to the sub-agent
    filtered_tools = []
    for tool in tools:
        if tool.metadata.name in ["search_code", "search_requirements"]:
            filtered_tools.append(tool)
    
    def generate_review(query: str) -> str:
        """Function to generate a comprehensive code review"""
        try:
            # Get PR data
            pr_data = get_pr_data(pr_id)
            
            # First create the agent with condensed instruction prompt
            review_agent = ReActAgent.from_tools(
                tools=filtered_tools,
                llm=OpenAI(model="o4-mini"),  # Use the same model as main agent
                system_prompt=REVIEW_SYSTEM_PROMPT,
                max_iterations=30,  # Allow more iterations for detailed review
                verbose=True  # Keep verbose to see thought process
            )
            
            # Turn off verbose temporarily while sending the large PR data message
            # This is a bit of a hack, but it should work to prevent printing the entire PR data
            original_verbose = review_agent.verbose
            review_agent.verbose = False
            
            # Send the PR data in the initial message
            initial_message = f"""
## PR DATA TO REVIEW

Here is the complete PR data that you should analyze for your review:

```json
{pr_data}
```

Please provide a comprehensive code review of this PR following the format in your instructions.
Please consider all files in PR data above and focus on the diffs of each file.
Do NOT ask for more PR information - it's provided above.
Begin your review immediately based on the data above and use your tools for additional context if needed.
"""
            
            print("Sending PR data in initial message (output suppressed)")
            
            # Get initial response with verbose off
            response = review_agent.chat(initial_message)
            
            # Restore verbose setting for any follow-up interactions
            review_agent.verbose = original_verbose
            
            # Return the review content
            print(f"Review tool response: {str(response)}")
            return str(response)
        except Exception as e:
            error_message = f"Error generating review: {str(e)}"
            print(error_message)
            return error_message
    
    # Create and return the tool
    return FunctionTool.from_defaults(
        name="start_review",
        description=(
            "Use this tool ONLY when the user requests to 'start review' or asks for a comprehensive code review. "
            "This tool performs a detailed analysis of the PR and generates a complete code review report. "
            "It examines all changed files, evaluates code quality, security, performance, and adherence to requirements."
        ),
        fn=generate_review
    ) 