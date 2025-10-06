from pocketflow import AsyncParallelBatchNode, Node
from utils.call_llm import call_llm, call_llm_async
from utils.progress import get_progress_tracker
from config import get_vector_db_config, get_system_config
import asyncio
import logging
import os
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class DocumentProcessorNode(AsyncParallelBatchNode):
    """Process retrieved documents in parallel to produce summaries and metadata"""
    
    async def prep_async(self, shared):
        unique_documents = shared.get("unique_documents", [])
        user_query = shared.get("user_query", "")
        retrieved_chunks = shared.get("retrieved_chunks", [])
        
        if not unique_documents or not user_query:
            logger.error("Missing documents or query for processing")
            return []
        
        # Enforce MAX_DOCS limit
        vdb_config = get_vector_db_config()
        max_docs = vdb_config.MAX_DOCS
        
        if len(unique_documents) > max_docs:
            logger.info(f"Limiting documents from {len(unique_documents)} to {max_docs}")
            unique_documents = unique_documents[:max_docs]
        
        # Group chunks by document
        chunks_by_document = {}
        for chunk in retrieved_chunks:
            file_name = chunk.get('metadata', {}).get('file_name')
            if file_name and file_name in unique_documents:
                if file_name not in chunks_by_document:
                    chunks_by_document[file_name] = []
                chunks_by_document[file_name].append(chunk)
        
        tracker = get_progress_tracker()
        tracker.update_stage("processing", 
                           f"Processing {len(unique_documents)} documents",
                           "Extracting relevant information in parallel")
        
        return [(doc, user_query, chunks_by_document.get(doc, [])) for doc in unique_documents]
    
    async def exec_async(self, doc_query_chunks):
        document_name, user_query, retrieved_chunks = doc_query_chunks
        
        try:
            # Read document content
            config = get_system_config()
            doc_path = os.path.join(config.DOCUMENTS_DIR, document_name)
            
            if not os.path.exists(doc_path):
                logger.warning(f"Document not found: {document_name}")
                return {
                    'doc_id': document_name,
                    'summary': f"Document not found: {document_name}",
                    'score': 0.0,
                    'metadata': {},
                    'failed': True
                }
            
            # Read full document
            from utils.file_processor import create_file_processor
            processor = create_file_processor()
            file_info = processor.process_file(doc_path)
            doc_content = file_info.get('content', '')
            doc_metadata = file_info.get('metadata', {})
            
            # Extract relevant chunks text for context
            chunk_texts = [chunk.get('text', '') for chunk in retrieved_chunks if chunk.get('text')]
            combined_chunks = "\n\n".join(chunk_texts[:5]) if chunk_texts else ""
            
            # Calculate average score from retrieved chunks
            scores = [chunk.get('score', 0.0) for chunk in retrieved_chunks if 'score' in chunk]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            
            # Create focused summarization prompt
            prompt = f"""You are a legal research assistant. Extract ONLY information directly relevant to the user's query from this legal case.

USER QUERY: {user_query}

LEGAL CASE: {document_name}

RETRIEVED RELEVANT SECTIONS:
{combined_chunks if combined_chunks else "Full document"}

FULL DOCUMENT CONTENT:
{doc_content[:8000]}

INSTRUCTIONS:
1. Extract only information that directly answers the user's query
2. Include specific quotes with paragraph references where relevant
3. Be concise - focus on key facts, holdings, and reasoning
4. If the case doesn't address the query, state that clearly
5. Provide ONE paragraph summary (maximum 150 words)

SUMMARY:"""

            # Call LLM asynchronously
            response = await call_llm_async(prompt)
            
            return {
                'doc_id': document_name,
                'summary': response.strip(),
                'score': avg_score,
                'metadata': doc_metadata,
                'failed': False
            }
            
        except Exception as e:
            logger.error(f"Error processing document {document_name}: {e}")
            return {
                'doc_id': document_name,
                'summary': f"Error processing document: {str(e)}",
                'score': 0.0,
                'metadata': {},
                'failed': True
            }
    
    async def post_async(self, shared, prep_res, exec_res_list):
        # Store processed documents
        processed_docs = [doc for doc in exec_res_list if not doc.get('failed', False)]
        failed_docs = [doc for doc in exec_res_list if doc.get('failed', False)]
        
        shared["processed_documents"] = exec_res_list
        shared["successful_documents"] = processed_docs
        shared["failed_documents"] = failed_docs
        
        logger.info(f"Document processing completed: {len(processed_docs)} successful, {len(failed_docs)} failed")
        
        tracker = get_progress_tracker()
        tracker.update_stage("processing_complete", 
                           f"Processed {len(processed_docs)} documents",
                           f"Ready for response composition")
        
        return "default"


class ResponseComposerNode(Node):
    """Compose final response from processed document summaries"""
    
    def prep(self, shared):
        user_query = shared.get("user_query", "")
        processed_documents = shared.get("processed_documents", [])
        language_instruction = shared.get("language_instruction", "Respond in clear, professional English.")
        
        return (user_query, processed_documents, language_instruction)
    
    def exec(self, prep_data):
        user_query, processed_documents, language_instruction = prep_data
        
        tracker = get_progress_tracker()
        tracker.update_stage("composing", 
                           "Composing final response", 
                           "Synthesizing information from all documents")
        
        if not processed_documents:
            return "I apologize, but I could not find any relevant legal cases for your query. Please try rephrasing your question or providing more specific details."
        
        # Filter successful documents and sort by score
        successful_docs = [doc for doc in processed_documents if not doc.get('failed', False)]
        
        if not successful_docs:
            return "I apologize, but there was an error processing the retrieved documents. Please try again."
        
        # Sort by relevance score (descending)
        successful_docs.sort(key=lambda x: x.get('score', 0.0), reverse=True)
        
        # Build case information with metadata
        case_summaries = []
        source_list = []
        
        for doc in successful_docs:
            doc_id = doc['doc_id']
            summary = doc['summary']
            metadata = doc.get('metadata', {})
            
            # Extract citation info
            citation = metadata.get('case_no', doc_id.replace('.txt', ''))
            case_title = metadata.get('case_title', '')
            pdf_url = metadata.get('pdf_url', '')
            
            # Create display text
            if case_title:
                display_text = f"{citation}: {case_title}"
            else:
                display_text = citation
            
            # Create hyperlink if PDF URL available
            if pdf_url and pdf_url.lower() != 'n/a':
                hyperlink = f"[{display_text}]({pdf_url})"
            else:
                hyperlink = display_text
            
            case_summaries.append(f"**{hyperlink}**\n{summary}")
            source_list.append(hyperlink)
        
        # Create final response prompt
        all_summaries_text = "\n\n".join(case_summaries)
        
        prompt = f"""You are a senior legal research assistant specializing in Supreme Court of Pakistan case law. Provide a focused response to a specific legal query.

🌐 LANGUAGE REQUIREMENT: {language_instruction}

USER QUERY: {user_query}

RELEVANT CASES AND SUMMARIES ({len(successful_docs)} cases):
{all_summaries_text}

INSTRUCTIONS:
1. Answer ONLY what the user asked - be direct and concise
2. Synthesize information from ALL {len(successful_docs)} cases provided
3. Ground ALL statements in the provided case law
4. When citing cases, use the case number format shown above (do NOT add extra formatting)
5. If cases have different outcomes, explain distinguishing factors
6. If the cases don't fully address the query, state that clearly

RESPONSE STRUCTURE:
## Direct Answer
[Provide a clear, concise answer to the user's query based on the cases]

## Legal Analysis
[Synthesize key findings from the cases - what patterns emerge?]

## Cases Referenced
[List all {len(successful_docs)} cases briefly showing their contribution to the answer]

RESPONSE:"""

        try:
            response = call_llm(prompt)
            
            # Add source footer
            footer = "\n\n---\n\n### 📑 Sources\n\n"
            for i, source in enumerate(source_list, 1):
                footer += f"{i}. {source}\n"
            
            final_response = response + footer
            return final_response
            
        except Exception as e:
            logger.error(f"Error composing response: {e}")
            return f"I apologize, but there was an error synthesizing the legal research results: {str(e)}"
    
    def post(self, shared, prep_res, exec_res):
        shared["final_response"] = exec_res
        
        tracker = get_progress_tracker()
        tracker.complete_session(True, "Legal research completed successfully")
        
        logger.info("Legal research process completed successfully")
        return "default"
