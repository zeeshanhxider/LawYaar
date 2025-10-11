import chromadb
from chromadb.utils import embedding_functions
import os
from typing import List, Dict, Any, Tuple
import logging
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_system_config, get_vector_db_config

logger = logging.getLogger(__name__)

class VectorDatabase:
    def __init__(self, persist_directory: str = None):
        """
        Initialize ChromaDB vector database
        
        Args:
            persist_directory: Directory to persist the database (uses config if None)
        """
        config = get_system_config()
        vdb_config = get_vector_db_config()
        
        persist_dir = persist_directory or config.CHROMA_DB_PATH
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # Check for GPU availability
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Initialize embedding function with optimizations
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=vdb_config.EMBEDDING_MODEL,
            device=device  # Use GPU if available
        )
        self.collection = None
        
        device_info = f"GPU ({torch.cuda.get_device_name(0)})" if device == "cuda" else "CPU"
        logger.info(f"Initialized vector database at {persist_dir} using {device_info}")
    
    def create_or_get_collection(self, collection_name: str = "legal_cases"):
        """
        Create or get existing collection
        
        Args:
            collection_name: Name of the collection
        """
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Retrieved existing collection: {collection_name}")
        except:
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Created new collection: {collection_name}")
        
        return self.collection
    
    def add_documents(self, texts: List[str], metadatas: List[Dict], ids: List[str]):
        """
        Add documents to the vector database with optimized batching
        
        Args:
            texts: List of document texts
            metadatas: List of metadata dictionaries
            ids: List of unique document IDs
        """
        if not self.collection:
            self.create_or_get_collection()
        
        # Add with optimized parameters
        # ChromaDB will generate embeddings internally
        self.collection.add(
            documents=texts,
            metadatas=metadatas,
            ids=ids
        )
        # Don't log for each mini-batch to reduce I/O overhead
    
    def search(self, query: str, n_results: int = 10, similarity_threshold: float = 0.5) -> List[Dict[str, Any]]:
        """
        Search for similar documents
        
        Args:
            query: Search query
            n_results: Number of results to return
            similarity_threshold: Minimum similarity score (0-1)
            
        Returns:
            List of search results with documents, metadata, and scores
        """
        if not self.collection:
            self.create_or_get_collection()
        
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        # Filter results by similarity threshold
        # Note: ChromaDB returns distances, we convert to similarity scores
        filtered_results = []
        
        for i, distance in enumerate(results['distances'][0]):
            # Convert distance to similarity score (assuming cosine distance)
            similarity_score = 1.0 - distance
            
            if similarity_score >= similarity_threshold:
                filtered_results.append({
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'score': similarity_score,
                    'id': results['ids'][0][i]
                })
        
        logger.info(f"Found {len(filtered_results)} documents above similarity threshold {similarity_threshold}")
        return filtered_results
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the collection
        
        Returns:
            Dictionary with collection statistics
        """
        if not self.collection:
            self.create_or_get_collection()
        
        count = self.collection.count()
        return {
            'total_documents': count,
            'collection_name': self.collection.name
        }
    
    def collection_exists(self, collection_name: str = "legal_cases") -> bool:
        """
        Check if a collection exists and has data
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            True if collection exists and has documents, False otherwise
        """
        try:
            collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            count = collection.count()
            logger.info(f"Collection '{collection_name}' exists with {count} documents")
            return count > 0
        except Exception as e:
            logger.info(f"Collection '{collection_name}' does not exist or is empty: {e}")
            return False

def create_vector_db() -> VectorDatabase:
    """
    Factory function to create vector database instance
    """
    return VectorDatabase()

if __name__ == "__main__":
    # Test the vector database
    db = create_vector_db()
    db.create_or_get_collection("test_collection")
    
    # Test data
    texts = ["This is a test document", "This is another test document"]
    metadatas = [{"source": "test1"}, {"source": "test2"}]
    ids = ["doc1", "doc2"]
    
    db.add_documents(texts, metadatas, ids)
    
    # Search test
    results = db.search("test document", n_results=5, similarity_threshold=0.5)
    print(f"Found {len(results)} results")
    for result in results:
        print(f"Score: {result['score']:.3f}, Text: {result['text'][:50]}...")
