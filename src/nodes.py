from pocketflow import Node, BatchNode, AsyncParallelBatchNode
from utils.call_llm import call_llm
from utils.vector_db import create_vector_db
from utils.embedding import get_embedding_service
from utils.file_processor import create_file_processor
from utils.chunking import create_chunker
from utils.progress import get_progress_tracker
from utils.cache_manager import create_cache_manager
from config import get_vector_db_config, get_system_config
import asyncio
import logging
import os
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class DocumentIngestionNode(BatchNode):
    """Process legal case files and extract text with metadata"""
    def prep(self, shared):
        config = get_system_config()
        documents_dir = shared.get("documents_directory", config.DOCUMENTS_DIR)
        if not os.path.exists(documents_dir):
            logger.error(f"Documents directory not found: {documents_dir}")
            return []
        
        file_paths = []
        for root, dirs, files in os.walk(documents_dir):
            for file in files:
                if file.endswith('.txt'):
                    file_paths.append(os.path.join(root, file))
        
        logger.info(f"Found {len(file_paths)} files to process")
        shared["_total_files"] = len(file_paths)
        shared["_processed_count"] = 0
        return file_paths
    
    def exec(self, file_path):
        processor = create_file_processor()
        file_info = processor.process_file(file_path)
        
        if not processor.validate_legal_case_format(file_info):
            logger.warning(f"File may not be properly formatted: {file_path}")
        
        return file_info
    
    def post(self, shared, prep_res, exec_res_list):
        shared["processed_files"] = exec_res_list
        shared["total_files_processed"] = len(exec_res_list)
        
        valid_files = sum(1 for f in exec_res_list if 'error' not in f)
        logger.info(f"Successfully processed {valid_files}/{len(exec_res_list)} files")
        
        return "default"

class VectorIndexCreationNode(BatchNode):
    """Create vector database index from processed documents"""
    def prep(self, shared):
        # Check if we can use cached vector DB
        config = get_system_config()
        vdb_config = get_vector_db_config()
        cache_manager = create_cache_manager()
        vector_db = create_vector_db()
        
        # Check if collection exists and cache is valid
        if vector_db.collection_exists(vdb_config.COLLECTION_NAME):
            logger.info("Existing collection found - checking for document changes...")
            
            # Use content-based hashing for reliable change detection
            has_changes, reason = cache_manager.has_changes(
                config.DOCUMENTS_DIR, 
                use_hash=True,  # Use content hashing instead of timestamps
                quick_check=False
            )
            
            if not has_changes:
                logger.info("✓ Using cached vector database - no document changes detected")
                shared["vector_db"] = vector_db
                vector_db.create_or_get_collection(vdb_config.COLLECTION_NAME)
                stats = vector_db.get_collection_stats()
                shared["total_chunks_indexed"] = stats['total_documents']
                shared["indexing_skipped"] = True
                return []  # Skip processing
            else:
                logger.info(f"⟳ Re-indexing required: {reason}")
        else:
            logger.info("⟳ No existing index found - creating new vector database")
        
        shared["indexing_skipped"] = False
        
        processed_files = shared.get("processed_files", [])
        if not processed_files:
            logger.error("No processed files found for indexing")
            return []
        
        documents_to_chunk = []
        for file_info in processed_files:
            if 'error' not in file_info and file_info.get('content'):
                documents_to_chunk.append(file_info)
        
        logger.info(f"Preparing {len(documents_to_chunk)} documents for chunking")
        shared["_total_docs_to_chunk"] = len(documents_to_chunk)
        shared["_chunked_count"] = 0
        return documents_to_chunk
    
    def exec(self, file_info):
        # Create chunker using settings configuration
        chunker = create_chunker()  # Uses settings.py configuration
        chunks = chunker.create_chunks(
            file_info['content'],
            metadata=file_info['metadata']
        )
        
        for chunk in chunks:
            chunk['metadata'].update({
                'file_name': file_info['file_name'],
                'file_path': file_info['file_path']
            })
        
        return chunks
    
    def post(self, shared, prep_res, exec_res_list):
        # If indexing was skipped (using cache), return early
        if shared.get("indexing_skipped", False):
            logger.info("Skipped indexing - using cached vector database")
            return "default"
        
        logger.info("Consolidating chunks from all documents...")
        all_chunks = []
        for chunk_list in exec_res_list:
            all_chunks.extend(chunk_list)
        
        vdb_config = get_vector_db_config()
        vector_db = create_vector_db()
        vector_db.create_or_get_collection(vdb_config.COLLECTION_NAME)
        
        # ChromaDB has a max batch size limit (around 5461)
        # We need to batch the insertion for large numbers of chunks
        BATCH_SIZE = 5000  # Safe batch size under ChromaDB's limit
        
        total_chunks = len(all_chunks)
        total_batches = (total_chunks + BATCH_SIZE - 1) // BATCH_SIZE
        
        logger.info("="*80)
        logger.info(f"INDEXING PROGRESS")
        logger.info(f"Total chunks to index: {total_chunks:,}")
        logger.info(f"Batch size: {BATCH_SIZE:,}")
        logger.info(f"Total batches: {total_batches}")
        logger.info("="*80)
        
        import time
        start_time = time.time()
        
        for batch_num, i in enumerate(range(0, total_chunks, BATCH_SIZE), 1):
            batch_start = time.time()
            batch_chunks = all_chunks[i:i + BATCH_SIZE]
            
            texts = [chunk['text'] for chunk in batch_chunks]
            metadatas = [chunk['metadata'] for chunk in batch_chunks]
            ids = [f"{chunk['metadata']['file_name']}_{chunk['metadata']['chunk_index']}" 
                   for chunk in batch_chunks]
            
            vector_db.add_documents(texts, metadatas, ids)
            
            batch_time = time.time() - batch_start
            elapsed = time.time() - start_time
            avg_time_per_batch = elapsed / batch_num
            remaining_batches = total_batches - batch_num
            eta = remaining_batches * avg_time_per_batch
            
            progress_pct = (batch_num / total_batches) * 100
            logger.info(f"✓ Batch {batch_num}/{total_batches} ({progress_pct:.1f}%) - "
                       f"{len(batch_chunks):,} chunks indexed in {batch_time:.1f}s - "
                       f"ETA: {eta/60:.1f} min")
        
        total_time = time.time() - start_time
        logger.info("="*80)
        logger.info(f"✓ INDEXING COMPLETE!")
        logger.info(f"Total time: {total_time/60:.1f} minutes")
        logger.info(f"Total chunks indexed: {total_chunks:,}")
        logger.info(f"Average speed: {total_chunks/total_time:.1f} chunks/second")
        logger.info("="*80)
        
        shared["vector_db"] = vector_db
        shared["total_chunks_indexed"] = total_chunks
        
        # Update cache after successful indexing (use content hashing)
        logger.info("Updating cache manifest with content hashes...")
        config = get_system_config()
        cache_manager = create_cache_manager()
        cache_manager.update_cache(config.DOCUMENTS_DIR, use_hash=True)
        logger.info(f"✓ Cache updated successfully")
        
        return "default"

class InitialRetrievalNode(Node):
    """Perform high-recall vector search for user query"""
    def prep(self, shared):
        user_query = shared.get("user_query", "")
        if not user_query:
            raise ValueError("No user query provided")
        
        vector_db = shared.get("vector_db")
        if not vector_db:
            vdb_config = get_vector_db_config()
            vector_db = create_vector_db()
            vector_db.create_or_get_collection(vdb_config.COLLECTION_NAME)
            shared["vector_db"] = vector_db
        
        return user_query
    
    def exec(self, user_query):
        tracker = get_progress_tracker()
        tracker.start_session(user_query)
        tracker.update_stage("retrieval", "Searching legal database", "Performing vector search")
        
        return user_query
    
    def post(self, shared, prep_res, exec_res):
        user_query = exec_res
        vector_db = shared["vector_db"]
        vdb_config = get_vector_db_config()
        
        # Add comprehensive logging for ChromaDB retrieval
        logger.info("="*80)
        logger.info("CHROMADB RETRIEVAL CHECK")
        logger.info("="*80)
        logger.info(f"Query being searched: {user_query}")
        logger.info(f"Max results to retrieve: {vdb_config.MAX_RESULTS}")
        logger.info(f"Similarity threshold: {vdb_config.SIMILARITY_THRESHOLD}")
        
        # Check if ChromaDB collection exists and has documents
        try:
            collection = vector_db.collection
            if collection:
                count = collection.count()
                logger.info(f"✅ ChromaDB collection found: {vdb_config.COLLECTION_NAME}")
                logger.info(f"✅ Total documents in collection: {count}")
                
                if count == 0:
                    logger.error("❌ CRITICAL: ChromaDB collection is EMPTY! No documents indexed.")
                    logger.error("Run 'python -m src.main --index' to populate the database")
                else:
                    logger.info(f"✅ ChromaDB is populated with {count} document chunks")
            else:
                logger.error("❌ CRITICAL: ChromaDB collection is None!")
        except Exception as e:
            logger.error(f"❌ Error checking ChromaDB collection: {e}")
        
        logger.info("Executing vector similarity search...")
        
        retrieved_chunks = vector_db.search(
            query=user_query,
            n_results=vdb_config.MAX_RESULTS,
            similarity_threshold=vdb_config.SIMILARITY_THRESHOLD
        )
        
        logger.info(f"✅ Retrieved {len(retrieved_chunks)} chunks from ChromaDB")
        
        if len(retrieved_chunks) == 0:
            logger.warning("⚠️ NO CHUNKS RETRIEVED! Possible reasons:")
            logger.warning("  1. ChromaDB is empty (not indexed)")
            logger.warning("  2. Query doesn't match any documents")
            logger.warning("  3. Similarity threshold too high")
            logger.warning("  4. Embedding model mismatch")
        else:
            logger.info(f"✅ Successfully found {len(retrieved_chunks)} matching chunks")
            # Log top 3 matches
            logger.info("Top 3 matching chunks:")
            for i, chunk in enumerate(retrieved_chunks[:3], 1):
                metadata = chunk.get('metadata', {})
                distance = chunk.get('distance', 'N/A')
                file_name = metadata.get('file_name', 'Unknown')
                chunk_text = chunk.get('document', '')[:100]
                logger.info(f"  {i}. File: {file_name}")
                # Fix the format string - calculate similarity first
                if isinstance(distance, float):
                    similarity = 1 - distance
                    logger.info(f"     Similarity: {similarity:.4f}")
                else:
                    logger.info(f"     Similarity: N/A")
                logger.info(f"     Preview: {chunk_text}...")
        
        logger.info("="*80)
        
        shared["retrieved_chunks"] = retrieved_chunks
        shared["retrieval_count"] = len(retrieved_chunks)
        
        tracker = get_progress_tracker()
        tracker.update_retrieval(len(retrieved_chunks))
        
        logger.info(f"Retrieved {len(retrieved_chunks)} chunks for query")
        return "default"

class DocumentExtractionNode(Node):
    """Extract unique document names from retrieved chunks"""
    def prep(self, shared):
        retrieved_chunks = shared.get("retrieved_chunks", [])
        return retrieved_chunks
    
    def exec(self, retrieved_chunks):
        unique_docs = set()
        for chunk in retrieved_chunks:
            file_name = chunk['metadata'].get('file_name')
            if file_name:
                unique_docs.add(file_name)
        
        unique_documents = list(unique_docs)
        logger.info(f"Found {len(unique_documents)} unique documents from {len(retrieved_chunks)} chunks")
        return unique_documents
    
    def post(self, shared, prep_res, exec_res):
        shared["unique_documents"] = exec_res
        shared["unique_document_count"] = len(exec_res)
        
        tracker = get_progress_tracker()
        tracker.update_stage("extraction", 
                           f"Extracted {len(exec_res)} unique documents", 
                           f"Processing {len(exec_res)} documents")
        
        return "default"