from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Union
import logging

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service with SentenceTransformer model
        
        Args:
            model_name: Name of the SentenceTransformer model to use
        """
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        logger.info(f"Initialized embedding service with model: {model_name}")
    
    def get_embedding(self, text: str) -> List[float]:
        """
        Get embedding for a single text
        
        Args:
            text: Input text to embed
            
        Returns:
            List of embedding values
        """
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Get embeddings for multiple texts efficiently
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embeddings
        """
        embeddings = self.model.encode(texts, convert_to_numpy=True, batch_size=32)
        return embeddings.tolist()
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate cosine similarity between two texts
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Cosine similarity score (0-1)
        """
        embeddings = self.model.encode([text1, text2], convert_to_numpy=True)
        
        # Calculate cosine similarity
        dot_product = np.dot(embeddings[0], embeddings[1])
        norm_a = np.linalg.norm(embeddings[0])
        norm_b = np.linalg.norm(embeddings[1])
        
        similarity = dot_product / (norm_a * norm_b)
        return float(similarity)
    
    def get_model_info(self) -> dict:
        """
        Get information about the embedding model
        
        Returns:
            Dictionary with model information
        """
        return {
            'model_name': self.model_name,
            'embedding_dimension': self.model.get_sentence_embedding_dimension(),
            'max_sequence_length': self.model.max_seq_length
        }

# Global embedding service instance
_embedding_service = None

def get_embedding_service() -> EmbeddingService:
    """
    Get singleton instance of embedding service
    
    Returns:
        EmbeddingService instance
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service

def get_embedding(text: str) -> List[float]:
    """
    Utility function to get embedding for text
    
    Args:
        text: Input text
        
    Returns:
        Embedding vector
    """
    service = get_embedding_service()
    return service.get_embedding(text)

if __name__ == "__main__":
    # Test the embedding service
    service = EmbeddingService()
    
    text = "This is a legal case about contract disputes"
    embedding = service.get_embedding(text)
    
    print(f"Text: {text}")
    print(f"Embedding dimension: {len(embedding)}")
    print(f"First 5 values: {embedding[:5]}")
    
    # Test similarity
    text1 = "Criminal law case involving theft"
    text2 = "Criminal proceedings about stolen property"
    similarity = service.calculate_similarity(text1, text2)
    print(f"\nSimilarity between:\n'{text1}'\nand\n'{text2}'\nScore: {similarity:.3f}")
    
    # Model info
    info = service.get_model_info()
    print(f"\nModel info: {info}")
