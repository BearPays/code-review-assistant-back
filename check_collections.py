import chromadb
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_collections.py <project_id>")
        return
    
    project_id = sys.argv[1]
    index_dir = Path("indexes") / project_id
    
    if not index_dir.exists():
        print(f"Error: Project index directory not found: {index_dir}")
        return
    
    print(f"Checking ChromaDB collections for project: {project_id}")
    try:
        client = chromadb.PersistentClient(path=str(index_dir))
        collections = client.list_collections()
        print(f"Found {len(collections)} collections:")
        for collection in collections:
            print(f"  - {collection.name}")
            print(f"    Count: {collection.count()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main() 