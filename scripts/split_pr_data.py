#!/usr/bin/env python3
"""
Script to split PR data JSON into separate files.
This script takes PR data JSON files and organizes them into a more structured
format with separate files for PR metadata and each modified file.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PR_DATA_DIR = os.path.join(DATA_DIR, "pr_data")

def split_pr_data(pr_data_file: str, output_dir: Optional[str] = None) -> str:
    """
    Split a PR data JSON file into separate files for metadata and each modified file.
    
    Args:
        pr_data_file: Path to the PR data JSON file
        output_dir: Directory where to save the split files (defaults to a directory named after the PR number)
    
    Returns:
        Path to the output directory
    """
    print(f"Processing PR data file: {pr_data_file}")
    
    # Load PR data
    with open(pr_data_file, 'r') as f:
        pr_data = json.load(f)
    
    pr_number = pr_data.get('pr_number')
    if not pr_number:
        raise ValueError("PR data must contain a 'pr_number' field")
    
    # Determine output directory
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(pr_data_file), f"pr_{pr_number}_split")
    
    # Create output directory structure
    os.makedirs(output_dir, exist_ok=True)
    modified_files_dir = os.path.join(output_dir, "modified_files")
    os.makedirs(modified_files_dir, exist_ok=True)
    
    print(f"Created output directory: {output_dir}")
    
    # Extract PR metadata
    pr_metadata = {
        "pr_number": pr_data.get("pr_number"),
        "title": pr_data.get("title"),
        "description": pr_data.get("description"),
        "state": pr_data.get("state"),
        "created_at": pr_data.get("created_at"),
        "updated_at": pr_data.get("updated_at"),
        "author": pr_data.get("author"),
        "comments": pr_data.get("comments", []),
        "reviews": pr_data.get("reviews", [])
    }
    
    # Add file summary information
    if "files" in pr_data:
        file_summaries = []
        for file_data in pr_data["files"]:
            file_summaries.append({
                "filename": file_data.get("filename"),
                "status": file_data.get("status"),
                "additions": file_data.get("additions", 0),
                "deletions": file_data.get("deletions", 0)
            })
        pr_metadata["file_summaries"] = file_summaries
    
    # Save PR metadata
    metadata_file = os.path.join(output_dir, "pr_metadata.json")
    with open(metadata_file, 'w') as f:
        json.dump(pr_metadata, f, indent=2)
    
    print(f"Saved PR metadata to: {metadata_file}")
    
    # Process each modified file
    if "files" in pr_data:
        for file_data in pr_data["files"]:
            filename = file_data.get("filename")
            if not filename:
                continue
            
            # Extract file data
            file_json = {
                "filename": filename,
                "status": file_data.get("status"),
                "additions": file_data.get("additions", 0),
                "deletions": file_data.get("deletions", 0),
                "total_changes": file_data.get("additions", 0) + file_data.get("deletions", 0),
                "diff": file_data.get("diff", "")
            }
            
            # Create directory structure matching the original file path
            file_dir = os.path.dirname(filename)
            target_dir = os.path.join(modified_files_dir, file_dir)
            
            # Create all necessary subdirectories
            if file_dir:
                os.makedirs(target_dir, exist_ok=True)
            
            # Save file data with original filename + .json extension
            json_filename = f"{os.path.basename(filename)}.json"
            file_output_path = os.path.join(modified_files_dir, file_dir, json_filename)
            
            with open(file_output_path, 'w') as f:
                json.dump(file_json, f, indent=2)
            
            print(f"Saved file data for {filename} to: {file_output_path}")
    
    print(f"Successfully split PR data into: {output_dir}")
    return output_dir

def process_pr_directory(directory: str) -> None:
    """
    Process all PR data JSON files in a directory.
    
    Args:
        directory: Directory containing PR data JSON files
    """
    print(f"Processing PR data files in directory: {directory}")
    
    # Find all JSON files in the directory
    json_files = [f for f in os.listdir(directory) if f.endswith('.json') and os.path.isfile(os.path.join(directory, f))]
    
    if not json_files:
        print(f"No JSON files found in {directory}")
        return
    
    print(f"Found {len(json_files)} JSON files")
    
    # Process each JSON file
    for json_file in json_files:
        try:
            split_pr_data(os.path.join(directory, json_file))
        except Exception as e:
            print(f"Error processing {json_file}: {e}")

# Run the script
# python scripts/split_pr_data.py --file data/project_2/pr_data/pr.json --output custom/output/directory

def main():
    """Main function to split PR data files."""
    parser = argparse.ArgumentParser(description='Split PR data JSON files into separate files')
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--file', '-f', type=str, help='Path to a single PR data JSON file')
    group.add_argument('--directory', '-d', type=str, help='Directory containing PR data JSON files')
    
    parser.add_argument('--output', '-o', type=str, help='Output directory (defaults to a directory named after the PR number)')
    
    args = parser.parse_args()
    
    try:
        if args.file:
            if not os.path.isfile(args.file):
                print(f"Error: File {args.file} does not exist")
                sys.exit(1)
            
            split_pr_data(args.file, args.output)
        
        elif args.directory:
            if not os.path.isdir(args.directory):
                print(f"Error: Directory {args.directory} does not exist")
                sys.exit(1)
            
            process_pr_directory(args.directory)
    
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
