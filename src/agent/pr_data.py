import os
import json
from pathlib import Path


def get_pr_data(project_name: str) -> str:
    """
    Fetches the PR data JSON file for a given project and returns it as a string.
    
    Args:
        project_name (str): The name of the project (e.g., 'project_1', 'project_2')
        
    Returns:
        str: The contents of the PR JSON file as a string, or an empty string if not found
        
    Raises:
        FileNotFoundError: If the PR data file doesn't exist
    """
    # Construct the path to the pr.json file
    data_dir = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data')))
    pr_json_path = data_dir / project_name / 'pr_data' / 'pr.json'
    
    # Check if the file exists
    if not pr_json_path.exists():
        raise FileNotFoundError(f"PR data file not found at {pr_json_path}")
    
    # Read and return the JSON content as a string
    with open(pr_json_path, 'r', encoding='utf-8') as f:
        pr_data = f.read()
    
    return pr_data


# For testing - only runs when script is executed directly
if __name__ == "__main__":
    try:
        # Test with project_2 as an example
        test_project = "project_2"
        pr_data = get_pr_data(test_project)
        print(f"Successfully loaded PR data for {test_project}")
        print(f"Data preview (first 200 chars): {pr_data[:200]}...")
    except Exception as e:
        print(f"Error: {e}")
