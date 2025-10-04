import re
from typing import List, Dict, Any, Optional
import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ChunkingConfig, ChunkingStrategy, get_chunking_config

logger = logging.getLogger(__name__)

class LegalTextChunker:
    def __init__(self, chunk_size: int = None, overlap: int = None, config: ChunkingConfig = None):
        """
        Initialize the legal text chunker with configuration
        
        Args:
            chunk_size: Target size for each chunk (overrides config)
            overlap: Number of characters to overlap (overrides config)
            config: ChunkingConfig object (if None, uses default from settings)
        """
        self.config = config or get_chunking_config()
        self.chunk_size = chunk_size or self.config.CHUNK_SIZE
        self.overlap = overlap or self.config.OVERLAP_SIZE
        self.strategy = self.config.STRATEGY
        
        logger.info(f"Initialized chunker: size={self.chunk_size}, overlap={self.overlap}, strategy={self.strategy.value}")
    
    def _split_by_legal_paragraphs(self, text: str) -> List[str]:
        """
        Split text by numbered legal paragraphs [1], [2], etc.
        This is the primary structure in Ontario Court decisions.
        
        Args:
            text: Input text to split
            
        Returns:
            List of paragraphs
        """
        # Pattern for numbered paragraphs like [1], [2], [10], [100]
        pattern = r'\n\s*\[\d+\]\s*'
        
        # Split by paragraph numbers
        parts = re.split(pattern, text)
        
        # Find all paragraph numbers to re-attach them
        numbers = re.findall(pattern, text)
        
        # Combine numbers with their content
        paragraphs = []
        for i, part in enumerate(parts):
            if i == 0 and part.strip():
                # Text before first paragraph number (usually header info)
                paragraphs.append(part.strip())
            elif i > 0 and i <= len(numbers):
                # Combine paragraph number with its content
                para_text = f"{numbers[i-1].strip()} {part.strip()}"
                if para_text.strip():
                    paragraphs.append(para_text)
        
        return paragraphs
    
    def _split_by_sections(self, text: str) -> List[str]:
        """
        Split text by major sections (Roman numerals, headings)
        
        Args:
            text: Input text to split
            
        Returns:
            List of sections
        """
        # Patterns for section headers
        section_patterns = [
            r'\n[IVX]+\.\s+[A-Z][^\n]+',  # Roman numerals: I. Introduction, II. Facts
            r'\n[A-Z][a-z]+:(?:\n|\s)',     # Single word headers: Introduction:, Facts:
            r'\n[A-Z][A-Z\s]+:(?:\n|\s)',   # All caps headers: FACTUAL CONTEXT:
        ]
        
        # Find all section headers
        sections = []
        for pattern in section_patterns:
            matches = list(re.finditer(pattern, text))
            if matches:
                # Split by these headers
                last_end = 0
                for match in matches:
                    if last_end < match.start():
                        sections.append(text[last_end:match.start()].strip())
                    last_end = match.start()
                sections.append(text[last_end:].strip())
                break
        
        return sections if sections else [text]
    
    def _group_paragraphs_semantically(self, paragraphs: List[str]) -> List[str]:
        """
        Group consecutive legal paragraphs based on configuration
        
        Args:
            paragraphs: List of individual paragraphs
            
        Returns:
            List of grouped paragraphs
        """
        if not paragraphs:
            return paragraphs
        
        # Apply strategy-specific processing
        if self.strategy == ChunkingStrategy.PRESERVE_PARAGRAPHS:
            # Keep paragraphs as-is, no splitting
            return paragraphs
            # # Group related paragraphs for better legal context
            # return self._group_related_legal_paragraphs(paragraphs)
        elif self.strategy == ChunkingStrategy.SPLIT_LARGE_PARAGRAPHS:
            # Split only paragraphs exceeding chunk size
            return self._selective_splitting(paragraphs)
        else:
            # Default to preserving paragraphs
            return paragraphs
    
    # def _group_related_legal_paragraphs(self, paragraphs: List[str]) -> List[str]:
    #     """
    #     Group related legal paragraphs to preserve context for better retrieval
        
    #     Args:
    #         paragraphs: List of individual paragraphs
            
    #     Returns:
    #         List of grouped paragraphs
    #     """
    #     if not paragraphs:
    #         return paragraphs
        
    #     grouped = []
    #     current_group = []
    #     current_size = 0
        
    #     for i, para in enumerate(paragraphs):
    #         para_size = len(para)
            
    #         # If adding this paragraph would exceed chunk size and we have content
    #         if current_size + para_size > self.chunk_size and current_group:
    #             # Save current group
    #             grouped.append('\n\n'.join(current_group))
    #             current_group = [para]
    #             current_size = para_size
    #         else:
    #             # Add to current group
    #             current_group.append(para)
    #             current_size += para_size
            
        
    #     # Add the last group
    #     if current_group:
    #         grouped.append('\n\n'.join(current_group))
        
    #     return grouped

    
    def _selective_splitting(self, paragraphs: List[str]) -> List[str]:
        """Split only large paragraphs, group small ones"""
        processed = []
        
        for para in paragraphs:
            if len(para) > self.config.CHUNK_SIZE:
                # Split this large paragraph
                splits = self._split_paragraph_fine_grained(para)
                processed.extend(splits)
            else:
                processed.append(para)
        
        # Now group the processed paragraphs
        return processed
    
    def _split_paragraph_fine_grained(self, paragraph: str) -> List[str]:
        """Split a single paragraph into smaller chunks"""
        if len(paragraph) <= self.chunk_size:
            return [paragraph]
        
        # Extract paragraph number if present
        para_num_match = re.match(r'^(\[\d+\]\s*)', paragraph)
        para_num = para_num_match.group(1) if para_num_match else ""
        content = paragraph[len(para_num):] if para_num else paragraph
        
        if self.config.SPLIT_ON_SENTENCES:
            # Split by sentences
            sentences = re.split(r'(?<=[.!?])\s+', content)
            chunks = []
            current_chunk = para_num  # Start with paragraph number
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) <= self.chunk_size:
                    current_chunk += (" " if current_chunk and current_chunk != para_num else "") + sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    # Keep paragraph number with continuation
                    current_chunk = para_num + "(cont.) " + sentence if self.config.PRESERVE_PARAGRAPH_NUMBERS else sentence
            
            if current_chunk:
                chunks.append(current_chunk)
            
            return chunks
        else:
            # Character-based splitting
            return self._character_based_chunking(paragraph)
    
    def create_chunks(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Create chunks from legal text using multiple strategies
        
        Args:
            text: Input text (content after metadata extraction)
            metadata: Optional metadata to attach to each chunk
            
        Returns:
            List of chunk dictionaries
        """
        if not text or len(text.strip()) == 0:
            return []
        
        chunks = []
        
        # Primary strategy: Split by numbered paragraphs
        paragraphs = self._split_by_legal_paragraphs(text)
        
        if len(paragraphs) > 1:
            # Group paragraphs semantically to create optimal chunks
            grouped_chunks = self._group_paragraphs_semantically(paragraphs)
            strategy_used = "legal_paragraphs"
        else:
            # Fallback: Try section-based splitting
            sections = self._split_by_sections(text)
            if len(sections) > 1:
                grouped_chunks = []
                for section in sections:
                    if len(section) <= self.chunk_size:
                        grouped_chunks.append(section)
                    else:
                        # Split large sections by character boundaries
                        grouped_chunks.extend(self._character_based_chunking(section))
                strategy_used = "sections"
            else:
                # Final fallback: Character-based chunking
                grouped_chunks = self._character_based_chunking(text)
                strategy_used = "character"
        
        # Add overlap between chunks for better context continuity
        final_chunks = self._add_overlap(grouped_chunks)
        
        # Convert to chunk dictionaries with metadata
        for i, chunk_text in enumerate(final_chunks):
            chunk_metadata = metadata.copy() if metadata else {}
            
            # Extract paragraph numbers if present
            para_numbers = re.findall(r'\[\d+\]', chunk_text)
            if para_numbers:
                chunk_metadata['paragraph_range'] = f"{para_numbers[0]}-{para_numbers[-1]}" if len(para_numbers) > 1 else para_numbers[0]
            
            chunk_metadata.update({
                'chunk_index': i,
                'chunk_count': len(final_chunks),
                'chunk_strategy': strategy_used,
                'chunk_size': len(chunk_text)
            })
            
            chunks.append({
                'text': chunk_text,
                'metadata': chunk_metadata
            })
        
        logger.info(f"Created {len(chunks)} chunks using {strategy_used} strategy")
        logger.info(f"Chunks: {chunks}")
        return chunks
    
    def _add_overlap(self, chunks: List[str]) -> List[str]:
        """
        Add overlap between chunks for better context continuity
        
        Args:
            chunks: List of text chunks
            
        Returns:
            List of chunks with overlap
        """
        if len(chunks) <= 1 or self.overlap <= 0:
            return chunks
        
        overlapped = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                # First chunk: no prefix overlap
                overlapped.append(chunk)
            else:
                # Add overlap from previous chunk
                prev_chunk = chunks[i-1]
                overlap_text = prev_chunk[-self.overlap:] if len(prev_chunk) > self.overlap else prev_chunk
                
                # Find a good break point (paragraph or sentence boundary)
                para_match = re.search(r'\n\s*\[\d+\]', overlap_text)
                if para_match:
                    overlap_text = overlap_text[para_match.start():]
                
                overlapped.append(overlap_text + chunk)
        
        return overlapped
    
    def _character_based_chunking(self, text: str) -> List[str]:
        """
        Fallback character-based chunking with overlap
        
        Args:
            text: Input text
            
        Returns:
            List of text chunks
        """
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            if end >= len(text):
                # Last chunk
                chunks.append(text[start:])
                break
            
            # Try to end at a word boundary
            chunk_end = end
            for i in range(end, max(start + self.chunk_size // 2, end - 100), -1):
                if text[i].isspace():
                    chunk_end = i
                    break
            
            chunks.append(text[start:chunk_end])
            start = chunk_end - self.overlap
        
        return chunks

def create_chunker(chunk_size: int = None, overlap: int = None, config: ChunkingConfig = None) -> LegalTextChunker:
    """
    Factory function to create a text chunker with configuration
    
    Args:
        chunk_size: Target size for each chunk (overrides config)
        overlap: Overlap between chunks (overrides config)
        config: ChunkingConfig object (if None, uses default from settings)
        
    Returns:
        LegalTextChunker instance
    """
    return LegalTextChunker(chunk_size, overlap, config)

if __name__ == "__main__":
    # Test the chunker
    chunker = LegalTextChunker(chunk_size=500, overlap=100)
    
    # Sample legal text
    sample_text = """
    ONTARIO COURT OF JUSTICE
    
    [1] This is the first paragraph of the legal decision.
    
    [2] This is the second paragraph discussing the facts of the case.
    The defendant was charged under section 123 of the Criminal Code.
    
    [3] The court must consider the following factors:
    (a) The nature of the offense
    (b) The circumstances of the defendant
    (c) The public interest
    
    [4] In conclusion, the court finds that the evidence supports the conviction.
    """
    
    chunks = chunker.create_chunks(sample_text, {'case_name': 'Test Case', 'year': '2024'})
    
    print(f"Created {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i + 1}:")
        print(f"Strategy: {chunk['metadata']['chunk_strategy']}")
        print(f"Size: {chunk['metadata']['chunk_size']}")
        print(f"Text: {chunk['text'][:100]}...")
