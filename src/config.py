from enum import Enum
from typing import Optional

class ChunkingStrategy(Enum):
    """Chunking strategies for legal documents"""
    PRESERVE_PARAGRAPHS = "preserve_paragraphs"  # Keep numbered paragraphs intact
    SPLIT_LARGE_PARAGRAPHS = "split_large_paragraphs"  # Split only large paragraphs

class ChunkingConfig:
    """Configuration for document chunking
    
    RECOMMENDED SETTINGS FOR EACH STRATEGY:
    
    1. PRESERVE_PARAGRAPHS (Keep legal context intact):
       - STRATEGY
       - OVERLAP_SIZE: 0 

    2. SPLIT_LARGE_PARAGRAPHS (Balanced approach - RECOMMENDED):
       - STRATEGY
       - CHUNK_SIZE: 200 (medium chunks)
       - OVERLAP_SIZE: 50-100 (moderate overlap)
    """
    
    # ==== CURRENT CONFIGURATION ====
    # Change STRATEGY to switch between modes
    STRATEGY = ChunkingStrategy.PRESERVE_PARAGRAPHS  
    
    # Basic chunking parameters 
    CHUNK_SIZE = 800  # Target size for each chunk in characters (increased for legal context)
    OVERLAP_SIZE = 150  # Number of characters to overlap between chunks (increased for better context)
    
    SPLIT_ON_SENTENCES = True  # Split by sentences when doing fine-grained splitting
    PRESERVE_PARAGRAPH_NUMBERS = True  # Keep [1], [2] markers with their content

class VectorDBConfig:
    """Configuration for vector database"""
    
    COLLECTION_NAME = "legal_cases"
    
    # Embedding model options (in order of speed vs quality):
    # "all-MiniLM-L6-v2" - FASTEST (6x faster, 384 dims, good quality)
    # "all-MiniLM-L12-v2" - FAST (3x faster, 384 dims, better quality)  
    # "all-mpnet-base-v2" - BALANCED (768 dims, best quality, slower)
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Optimized for speed (was all-mpnet-base-v2)
    
    SIMILARITY_THRESHOLD = 0.01  # Very low threshold to capture more results (was 0.05, actual scores: 0.05-0.23)
    MAX_RESULTS = 100  # Increased for better coverage of legal concepts
    MAX_DOCS = 4  # Maximum number of documents to process for final response


class LLMConfig:
    """Configuration for LLM settings"""
    
    # Default LLM provider and model
    PROVIDER = "openai"  # Options: "openai", "gemini"
    MODEL = "gpt-4o-mini"  # Default model (fast and cost-effective)
    
    # Available models for each provider
    OPENAI_MODELS = [
        "gpt-4o",          # Most capable, multimodal
        "gpt-4o-mini",     # Fast and cost-effective (recommended)
        "gpt-4-turbo",     # Previous generation
        "gpt-3.5-turbo"    # Legacy, cheapest
    ]
    
    GEMINI_MODELS = [
        "gemini-2.5-pro",        # Most advanced thinking model
        "gemini-2.5-flash",      # Best price-performance
        "gemini-2.5-flash-lite"  # Fastest, cost-efficient
    ]
    
    MAX_RETRIES = 3  # Maximum retries for LLM calls
    RETRY_WAIT = 10  # Seconds to wait between retries
    
    # Parallel processing
    MAX_PARALLEL_PRUNING = 10  # Max concurrent pruning agents
    MAX_PARALLEL_READING = 10  # Max concurrent reading agents


class SystemConfig:
    """General system configuration"""
    
    # Directories (use absolute paths to avoid issues when running from different directories)
    import os
    from pathlib import Path
    
    # Get project root (parent of src directory)
    _PROJECT_ROOT = Path(__file__).parent.parent
    
    DOCUMENTS_DIR = str(_PROJECT_ROOT / "src" / "assets" / "data")
    CHROMA_DB_PATH = str(_PROJECT_ROOT / "chroma_db")  # Use project root chroma_db, not src/chroma_db
    
    # Logging
    LOG_LEVEL = "INFO"
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Progress tracking
    ENABLE_PROGRESS_TRACKING = True
    PROGRESS_UPDATE_INTERVAL = 0.5  # Seconds between progress updates
    
    # Performance optimization
    USE_CONTENT_HASH_CACHE = True  # Use content hashing for cache (slower first time, but more reliable)
    PARALLEL_WORKERS = 4  # Number of parallel workers for file processing (0 = auto-detect)
    
    # Indexing optimization
    INDEXING_BATCH_SIZE = 100  # Smaller batches = faster embedding generation (don't change unless needed)
    SHOW_PROGRESS_EVERY_N_BATCHES = 10  # Show progress every N batches (reduce logging overhead)


# Convenience functions to get configurations
def get_chunking_config() -> ChunkingConfig:
    """Get chunking configuration"""
    return ChunkingConfig()

def get_vector_db_config() -> VectorDBConfig:
    """Get vector database configuration"""
    return VectorDBConfig()

def get_llm_config() -> LLMConfig:
    """Get LLM configuration"""
    return LLMConfig()

def get_system_config() -> SystemConfig:
    """Get system configuration"""
    return SystemConfig()


# Example usage and testing
if __name__ == "__main__":
    print("Current Chunking Configuration:")
    print("-" * 40)
    
    config = get_chunking_config()
    print(f"Chunk Size: {config.CHUNK_SIZE}")
    print(f"Overlap Size: {config.OVERLAP_SIZE}")
    print(f"Strategy: {config.STRATEGY.value}")
    print(f"Split on Sentences: {config.SPLIT_ON_SENTENCES}")
    print(f"Preserve Paragraph Numbers: {config.PRESERVE_PARAGRAPH_NUMBERS}")
    
    print("\nVector DB Configuration:")
    print("-" * 40)
    vdb_config = get_vector_db_config()
    print(f"Collection Name: {vdb_config.COLLECTION_NAME}")
    print(f"Similarity Threshold: {vdb_config.SIMILARITY_THRESHOLD}")
    print(f"Max Results: {vdb_config.MAX_RESULTS}")
