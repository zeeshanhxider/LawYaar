from pocketflow import Node, BatchNode, AsyncParallelBatchNode
from utils.call_llm import call_llm
from utils.vector_db import create_vector_db
from utils.embedding import get_embedding_service
from utils.file_processor import create_file_processor
from utils.chunking import create_chunker
from utils.progress import get_progress_tracker
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
        processed_files = shared.get("processed_files", [])
        if not processed_files:
            logger.error("No processed files found for indexing")
            return []
        
        documents_to_chunk = []
        for file_info in processed_files:
            if 'error' not in file_info and file_info.get('content'):
                documents_to_chunk.append(file_info)
        
        logger.info(f"Preparing {len(documents_to_chunk)} documents for chunking")
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
        logger.info(f"Preparing to index {total_chunks} chunks in batches of {BATCH_SIZE}")
        
        for i in range(0, total_chunks, BATCH_SIZE):
            batch_chunks = all_chunks[i:i + BATCH_SIZE]
            
            texts = [chunk['text'] for chunk in batch_chunks]
            metadatas = [chunk['metadata'] for chunk in batch_chunks]
            ids = [f"{chunk['metadata']['file_name']}_{chunk['metadata']['chunk_index']}" 
                   for chunk in batch_chunks]
            
            vector_db.add_documents(texts, metadatas, ids)
            logger.info(f"Indexed batch {i//BATCH_SIZE + 1}: {len(batch_chunks)} chunks")
        
        shared["vector_db"] = vector_db
        shared["total_chunks_indexed"] = total_chunks
        
        logger.info(f"Successfully indexed all {total_chunks} chunks in vector database")
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
        
        retrieved_chunks = vector_db.search(
            query=user_query,
            n_results=vdb_config.MAX_RESULTS,
            similarity_threshold=vdb_config.SIMILARITY_THRESHOLD
        )
        
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