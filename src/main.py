import asyncio
import logging
import os
from dotenv import load_dotenv
from flow import create_offline_indexing_flow, create_online_research_flow
from utils.progress import get_progress_tracker

# Load environment variables from .env file in project root
project_root = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(project_root, '.env'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_offline_indexing():
    """
    Run the offline indexing process to create vector database from legal documents
    """
    print("\n" + "="*60)
    print("VECTOR DATABASE INITIALIZATION")
    print("="*60)
    
    # Create shared store for offline processing
    shared = {
        "documents_directory": "src/assets/data",
        "processed_files": [],
        "total_files_processed": 0,
        "vector_db": None,
        "total_chunks_indexed": 0,
        "indexing_skipped": False
    }
    
    # Create and run offline flow
    offline_flow = create_offline_indexing_flow()
    offline_flow.run(shared)
    
    if shared.get("indexing_skipped", False):
        print("\n✓ Using cached vector database (no document changes detected)")
        print(f"  Total chunks available: {shared['total_chunks_indexed']}")
    else:
        print("\n✓ Indexing completed!")
        print(f"  Files processed: {shared['total_files_processed']}")
        print(f"  Chunks indexed: {shared['total_chunks_indexed']}")
        print(f"  Cache updated for future runs")
    
    print("="*60)
    
    return shared

async def run_online_research(user_query: str, vector_db=None):
    """
    Run the online research process for a user query
    
    Args:
        user_query: The legal research query
        vector_db: Pre-built vector database (optional)
    """
    print(f"Starting legal research for: '{user_query}'")
    
    # Setup progress tracking
    def progress_callback(progress_data):
        stage = progress_data.get('stage', 'unknown')
        status = progress_data.get('status', '')
        activity = progress_data.get('current_activity', '')
        
        print(f"{stage.upper()}: {status}")
        if activity and activity != status:
            print(f"{activity}")
        
        # Show reading progress
        if 'documents_being_read' in progress_data and progress_data['documents_being_read']:
            completed = progress_data.get('completed_readings', 0)
            total = progress_data.get('total_readings', 0)
            if total > 0:
                print(f"Reading progress: {completed}/{total}")
                
                # Show current document being read
                if completed < total:
                    current_doc = progress_data['documents_being_read'][completed] if completed < len(progress_data['documents_being_read']) else "Unknown"
                    print(f"Currently reading: {current_doc}")
    
    # Register progress callback
    tracker = get_progress_tracker()
    tracker.register_callback(progress_callback)
    
    # Create shared store for online processing
    shared = {
        "user_query": user_query,
        "vector_db": vector_db,
        "retrieved_chunks": [],
        "retrieval_count": 0,
        "unique_documents": [],
        "unique_document_count": 0,
        "processed_documents": [],
        "successful_documents": [],
        "failed_documents": [],
        "final_response": ""
    }
    
    # Create and run online flow
    online_flow = create_online_research_flow()
    await online_flow.run_async(shared)
    
    print("\n" + "="*80)
    print("LEGAL RESEARCH RESULTS")
    print("="*80)
    print(f"Query: {user_query}")
    print(f"Documents found: {shared['retrieval_count']}")
    print(f"Unique documents: {shared['unique_document_count']}")
    print(f"Processed documents: {len(shared['successful_documents'])}")
    print("\nFinal Response:")
    print("-" * 40)
    print(shared['final_response'])
    
    return shared

async def main():
    """
    Main function to run the legal AI system
    """
    print("Legal AI Research System")
    print("=" * 50)
    
    # Check if we have documents
    documents_dir = "src/assets/data"
    if not os.path.exists(documents_dir):
        print(f"Documents directory not found: {documents_dir}")
        print("Please ensure you have legal case files in the src/assets/data directory")
        return
    
    # Count available documents
    txt_files = [f for f in os.listdir(documents_dir) if f.endswith('.txt')]
    print(f"Found {len(txt_files)} legal case files")
    
    if len(txt_files) == 0:
        print("No .txt files found in documents directory")
        return
    
    # Run offline indexing first
    try:
        offline_results = run_offline_indexing()
        vector_db = offline_results.get("vector_db")
    except Exception as e:
        print(f"Error during indexing: {e}")
        logger.error(f"Indexing error: {e}", exc_info=True)
        return
    
    print("\n" + "="*50)
    
    # Interactive query loop
    while True:
        print("\nEnter your legal research query (or 'quit' to exit):")
        user_input = input("> ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break
        
        if not user_input:
            print("Please enter a valid query.")
            continue
        
        try:
            # Run online research
            await run_online_research(user_input, vector_db)
        except Exception as e:
            print(f"Error during research: {e}")
            logger.error(f"Research error: {e}", exc_info=True)
            continue

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())