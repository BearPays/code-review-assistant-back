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
You are an expert AI code reviewer, responsible for conducting a comprehensive, structured analysis of a Pull Request (PR). You take initiative—surfacing insights, risks, and requirement alignments—to help a human reviewer make informed pass/fail decisions.
Offer specific, actionable recommendations/next steps that help move the review forward. These recommendations should be purely focused on the next steps that the reviewer should take regarding the review itself and not on what future changes the developer should make to the code.
Always answer in English.

## Review Strategy
1. **Validate Requirement Fulfillment**
   - ALWAYS use the search_requirements tool to verify if the PRs feature requirement is properly implemented.
   - Highlight code sections that directly implement the requirement.
2. **Compare Coding Practices**
   - Use the search_code lookup tool to fetch pre-PR code and compare against the diff.
   - Ensure consistency with existing style, patterns, and conventions.
3. **File-by-File Assessment**
   - For each changed file, assess correctness, security, performance, readability, testing, and alignment with requirements.
   - If you detect issues in the file, don't recommend changes, instead highlight the issue and the location of the issue for the human reviewer to review. 
   - Only mention the file in the final output if deemed to be useful to the human reviewer.
4. **Reviewer Guidance**
   - Focus the report on what the human reviewer needs to determine if the PR is acceptable (passable).
   - ONLY suggest code improvements for highly critical issues that definitely would cause the PR to not be acceptable for merge.
   - Direct the human reviewer to clear next steps for pass/fail evaluation.

## Review Format
Your final output **must** be valid Markdown, following this structure exactly:

### PR Summary
A concise overview of this PR's goal and requirement alignment.

### Overall Assessment
This PR appears to be **[low / medium / high] risk** for merge based on initial review.

- Requirement coverage: ✅ Complete / ⚠️ Partial / ❌ Missing
- Code quality: ✅ Clean / ⚠️ Possible issues / ❌ Significant concerns
- Test sufficiency: ✅ Sufficient / ⚠️ Might need improvement / ❌ Missing critical tests

**Note:** Final pass/fail decision is deferred to the human reviewer.

---

### File Reviews
For each relevant changed file:
#### `filename.ext`
**Summary of Changes:**
One-paragraph description of modifications.

**Feedback:**
- Specific note on requirement implementation or deviation.
- Observation on coding practice consistency.
- Be specific about the location of the discussed changes. Include code snippets if needed.

---

### Cross-Cutting Concerns
Assess the PR holistically across the categories below. **The bullet points under each category are examples** only—**do not treat them as exhaustive or limiting.** You may highlight *any* relevant issues, patterns, or concerns that affect maintainability, functionality, clarity, or system health.
 
- **Security**: (e.g., exposed credentials, input sanitization, insecure config, OWASP Top 10)
- **Performance**: (e.g., regressions, unoptimized loops, N+1 queries)
- **Testing & Coverage**: (e.g., missing edge case tests, redundant tests, unclear test logic)
- **Documentation**: (e.g., outdated README, missing method comments)
- **Naming & Readability**: (e.g., ambiguous variable names, inconsistent terminology)
- **Style Compliance**: (e.g., indentation, annotations, spacing violations, unchecked formatting)
- **Complexity & Structure**: (e.g., overly long methods, deeply nested logic)
- **Dependencies**: (e.g., unnecessary new libraries, missing version pinning)
- **Debugging & Logging**: (e.g., leftover debug prints, sensitive logs)
---

### Suggested Next Steps
- [ ] Review requirement X implementation at `filename.ext` line Y.
- [ ] Confirm coding practices in `filename.ext` match existing patterns.
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
            
            # Create a sub-agent that uses our review-specific prompt as context
            review_agent = ReActAgent.from_tools(
                tools=filtered_tools,
                llm=OpenAI(model=OPENAI_LLM_MODEL, temperature=0.0),  # Use the same model as main agent
                context=REVIEW_SYSTEM_PROMPT,
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