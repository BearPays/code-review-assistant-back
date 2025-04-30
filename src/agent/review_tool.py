import os
from typing import List, Dict, Optional
from llama_index.core import Settings
from llama_index.core.agent import ReActAgent
from llama_index.core.tools import QueryEngineTool, FunctionTool, ToolMetadata
from llama_index.llms.openai import OpenAI

from .pr_data import get_pr_data
from .model_constants import OPENAI_LLM_MODEL

# Review-specific system prompt that focuses on instructions rather than data
REVIEW_SYSTEM_PROMPT = """
You are an expert AI code reviewer, responsible for conducting a comprehensive, structured analysis of a Pull Request (PR).

<role_and_purpose>

Your final output should be a markdown document following the exact format provided in the <review_format> section below.

Your role is to serve as a lead reviewer, performing a **deep and detailed evaluation** of the changes introduced in the PR.  
You take initiative — not only identifying issues but also offering concrete suggestions and next steps.

The report you produce will be handed off to a **human developer or reviewer**, who will use your findings to guide their own review process.  
Your job is to **surface insights, risks, and improvement opportunities** to help them make informed decisions quickly and confidently.

Your responsibilities include:
- Understanding the intent of the PR by examining its title, description, and related requirements.
- Analyzing each file's changes for quality, correctness, and broader impact.
- Using tools to investigate surrounding code and feature expectations as needed.
- Delivering a **clear, structured review** that highlights what the human reviewer should focus on.

<tool_calling>

You have tools at your disposal to help conduct your review:
- `search_code`: Use this to inspect the **original version** of any file before changes. Use it to understand the surrounding context, code style, conventions, and implementation logic that predate the PR.
- `search_requirements`: Use this to find **feature requirements**, user stories, or acceptance criteria that may explain why the PR was created and what it is supposed to accomplish.

Use tools **only when necessary**, and only when you need additional context. Always explain what you are doing and why before using a tool.

<review_strategy>

Conduct the review in the following order:

1. **Understand the purpose of the PR**
   - Analyze the title and description
   - Optionally use `search_requirements` to validate intent

2. **Gather context from the codebase**
   - Use `search_code` to explore original code relevant to the changes
   - Identify coding patterns, standards, or logic that relate to the PR

3. **Perform a detailed file-by-file review**
   - Highlight correctness, design, security, performance, readability, testing, and alignment with requirements
   - Make sure to use all tools available to you to get a holistic understanding of the changes

4. **Present clear findings**
   - Structure your output in a way that helps the human reviewer quickly spot areas of concern and follow up on your suggestions

<review_format>

Your final output must follow this format exactly and MUST be in proper Markdown syntax:
### PR Summary
A short overview of what this PR aims to do and why, based on title, description, and feature requirements.

### Overall Assessment
An executive summary. Does the PR meet expectations? Are there major issues? Can it be merged as-is?

---

### File Reviews
For each changed file (where changes need to be reviewed):
- there is no need to address changes that are not relevant

#### `filename.go`
**Summary of Changes:**  
One-paragraph summary of what was modified.

**Feedback:**
- [Line 42] Potential off-by-one bug when indexing `results`
- [Line 10] Good use of abstraction via helper function
- [Line 56] Consider breaking up this function to improve readability

---

### Cross-Cutting Concerns

#### Security & Performance
- Mention any design flaws, input validation gaps, or performance regressions

#### Testing
- State if tests are present, meaningful, and sufficient
- Mention edge cases that are uncovered

#### Documentation
- Note if docs (inline, README, comments) are missing or outdated

#### Adherence to Requirements
- Confirm if the PR fulfills its stated goal
- Call out any drift from acceptance criteria

---

### Suggested Follow-Ups
Summarize recommended next steps for the human reviewer. For example:
- [ ] Investigate potential bug in `utils/parser.go` line 42
- [ ] Ask author to clarify purpose of new `auth_token_strategy` abstraction
- [ ] Confirm if all endpoints have adequate test coverage


<guidelines>

- Be specific. Do not give general praise or vague criticism.
- Always ground your comments in concrete lines, behaviors, or omissions.
- Suggest practical improvements where problems are found.
- Identify edge cases, unhandled inputs, or overlooked scenarios.
- Be objective and constructive — your goal is to elevate the quality of the code.
- Format code examples in fenced code blocks with language tags (`python`, `go`, `ts`, etc.).
- Always communicate in English.
- Your entire response must be in properly formatted Markdown. All section headings, bullet points, emphasis, and code blocks should use Markdown syntax.
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
                llm=OpenAI(model=OPENAI_LLM_MODEL, temperature=0.0),  # Use the same model as main agent
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
            
            # Format the return statement to improve clarity and readability
            return ("The following is the compiled code review. Return it directly to the user without modifying the content or language. "
                    "Ensure the response is returned as plain markdown text (not as a markdown code block), so the frontend can compile and format it.\n\n---\n\n" + str(response))
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