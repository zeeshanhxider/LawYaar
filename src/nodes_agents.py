from pocketflow import AsyncParallelBatchNode, Node
from utils.call_llm import call_llm, call_llm_async
from utils.progress import get_progress_tracker
from config import get_system_config
import asyncio
import logging
import os
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

def classify_legal_query_type(user_query: str) -> dict:
    """Use an LLM agent to intelligently classify the legal query and determine response structure"""
    
    classification_prompt = f"""You are a legal research classification agent. Analyze the user's legal query and determine:
1. The primary legal area/topic
2. What type of information the user is seeking
3. The most appropriate response structure

USER QUERY: {user_query}

ANALYSIS INSTRUCTIONS:
- Consider the intent behind the query, not just keywords
- Think about what a lawyer would actually need to know
- Determine the most focused response structure

AVAILABLE QUERY TYPES:
- sentencing: Questions about penalties, sentences, punishment factors
- bail: Questions about release, detention, custody decisions
- evidence: Questions about admissibility, Charter violations, evidence law
- procedure: Questions about legal processes, motions, applications
- definition: Questions seeking definitions, elements, legal concepts
- precedent: Questions about case authority, binding precedents
- factors: Questions about criteria, considerations, tests used by courts
- general: Broad questions requiring comprehensive analysis

RESPONSE FORMAT (JSON):
{{
    "query_type": "most_appropriate_type",
    "confidence": 0.95,
    "reasoning": "Brief explanation of why this classification fits",
    "focus_areas": ["key area 1", "key area 2", "key area 3"],
    "response_sections": ["section 1", "section 2", "section 3"]
}}

Respond with ONLY the JSON object:"""

    try:
        response = call_llm(classification_prompt)
        
        # Extract JSON from response
        import json
        import re
        
        # Try to find JSON in the response
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            classification = json.loads(json_match.group())
            
            # Validate required fields
            required_fields = ['query_type', 'confidence', 'reasoning', 'focus_areas', 'response_sections']
            if all(field in classification for field in required_fields):
                return classification
        
        # Fallback if parsing fails
        logger.warning(f"Failed to parse classification response: {response}")
        return {
            "query_type": "general",
            "confidence": 0.5,
            "reasoning": "Classification parsing failed, using general approach",
            "focus_areas": ["legal analysis", "case law", "precedents"],
            "response_sections": ["Direct Answer", "Legal Analysis", "Cases Referenced"]
        }
        
    except Exception as e:
        logger.error(f"Error in query classification: {e}")
        # Fallback classification
        return {
            "query_type": "general", 
            "confidence": 0.3,
            "reasoning": "Classification agent failed, using general approach",
            "focus_areas": ["legal analysis", "case law", "precedents"],
            "response_sections": ["Direct Answer", "Legal Analysis", "Cases Referenced"]
        }

class QueryClassificationNode(Node):
    """Classify the legal query once at the beginning of the process"""
    
    def prep(self, shared):
        user_query = shared.get("user_query", "")
        if not user_query:
            logger.error("No user query provided for classification")
            return None
        return user_query
    
    def exec(self, user_query):
        if not user_query:
            return None
        
        logger.info(f"Classifying query: {user_query[:100]}...")
        classification = classify_legal_query_type(user_query)
        logger.info(f"Query classified as '{classification.get('query_type')}' with confidence {classification.get('confidence', 0):.2f}")
        return classification
    
    def post(self, shared, prep_res, exec_res):
        if exec_res:
            shared["query_classification"] = exec_res
        else:
            # Fallback classification if something went wrong
            shared["query_classification"] = {
                "query_type": "general",
                "confidence": 0.3,
                "reasoning": "Classification failed, using general approach",
                "focus_areas": ["legal analysis", "case law", "precedents"],
                "response_sections": ["Direct Answer", "Legal Analysis", "Cases Referenced"]
            }
        return "default"

class PruningAgentNode(AsyncParallelBatchNode):
    """Determine if documents are relevant to the query using parallel agents"""
    
    async def prep_async(self, shared):
        unique_documents = shared.get("unique_documents", [])
        user_query = shared.get("user_query", "")
        retrieved_chunks = shared.get("retrieved_chunks", [])
        
        if not unique_documents or not user_query:
            logger.error("Missing documents or query for pruning")
            return []
        
        # Group retrieved chunks by document for pruning analysis
        chunks_by_document = {}
        for chunk in retrieved_chunks:
            file_name = chunk.get('metadata', {}).get('file_name')
            if file_name and file_name in unique_documents:
                if file_name not in chunks_by_document:
                    chunks_by_document[file_name] = []
                chunks_by_document[file_name].append(chunk)
        
        tracker = get_progress_tracker()
        tracker.update_stage("pruning", 
                           f"Analyzing relevance of {len(unique_documents)} documents",
                           "Running parallel pruning agents with retrieved chunks")
        tracker.update_pruning(0, len(unique_documents))
        
        # Return document name, query, and its retrieved chunks
        return [(doc, user_query, chunks_by_document.get(doc, [])) for doc in unique_documents]
    
    async def exec_async(self, doc_query_chunks):
        document_name, user_query, retrieved_chunks = doc_query_chunks
        
        if not retrieved_chunks:
            logger.warning(f"No retrieved chunks found for document: {document_name}")
            return (document_name, False, "No retrieved chunks available for analysis")
        
        # Combine all retrieved chunk texts for this document
        chunk_texts = []
        for chunk in retrieved_chunks:
            chunk_text = chunk.get('text', '')
            if chunk_text:
                chunk_texts.append(chunk_text)
        
        if not chunk_texts:
            logger.warning(f"No chunk text found for document: {document_name}")
            return (document_name, False, "No chunk text available for analysis")
        
        # Combine chunks with separators
        combined_chunk_content = "\n\n--- CHUNK SEPARATOR ---\n\n".join(chunk_texts)
        
        # Create pruning prompt using the actual retrieved chunks
        pruning_prompt = f"""You are a legal research assistant. Your task is to determine if a legal case document is relevant to a specific query based on the chunks that were retrieved from the vector database.

QUERY: {user_query}

DOCUMENT: {document_name}
RETRIEVED CHUNKS FROM VECTOR DATABASE:
{combined_chunk_content}

ANALYSIS CONTEXT:
- These chunks were already identified as potentially relevant by vector similarity
- You are evaluating if the document as a whole (represented by these chunks) addresses the user's query
- Consider both direct relevance and indirect relevance (precedential value, similar legal principles)

INSTRUCTIONS:
1. Carefully analyze if these retrieved chunks show that this legal case's content is STRICTLY RELEVANT TO the USER QUERY
2. Consider both direct relevance and indirect relevance (precedential value)
3. Respond with ONLY "YES" or "NO" followed by a brief one-line explanation


RESPONSE FORMAT:
YES/NO - [Brief explanation for this]


RESPONSE:"""

        try:
            logger.info(f"Pruning {document_name} using {len(chunk_texts)} retrieved chunks ({sum(len(chunk) for chunk in chunk_texts)} total characters)")
            response = await call_llm_async(pruning_prompt)
            is_relevant = response.strip().upper().startswith("YES")
            
            return (document_name, is_relevant, response.strip())
        except Exception as e:
            logger.error(f"Error in pruning agent for {document_name}: {e}")
            return (document_name, False, f"Error: {str(e)}")
    
    async def post_async(self, shared, prep_res, exec_res_list):
        pruning_results = {}
        relevant_documents = []
        
        for doc_name, is_relevant, explanation in exec_res_list:
            pruning_results[doc_name] = {
                'relevant': is_relevant,
                'explanation': explanation
            }
            if is_relevant:
                relevant_documents.append(doc_name)
        
        shared["pruning_results"] = pruning_results
        shared["relevant_documents"] = relevant_documents
        
        tracker = get_progress_tracker()
        tracker.update_pruning(len(exec_res_list), len(exec_res_list))
        tracker.update_stage("reading_prep", 
                           f"Selected {len(relevant_documents)} relevant documents",
                           f"Preparing to read {len(relevant_documents)} documents")
        
        logger.info(f"Pruning completed: {len(relevant_documents)}/{len(exec_res_list)} documents relevant")
        return "default"

class ReadingAgentNode(AsyncParallelBatchNode):
    """Extract relevant information from filtered documents using parallel agents"""
    
    async def prep_async(self, shared):
        relevant_documents = shared.get("relevant_documents", [])
        user_query = shared.get("user_query", "")
        retrieved_chunks = shared.get("retrieved_chunks", [])
        
        if not relevant_documents or not user_query:
            logger.error("No relevant documents or query for reading")
            return []
        
        # Calculate chunk information for each document
        chunk_info = {}
        for doc in relevant_documents:
            # Count total chunks for this document
            doc_chunks = [chunk for chunk in retrieved_chunks 
                         if chunk.get('metadata', {}).get('file_name') == doc]
            total_chunks = len(doc_chunks)
            
            # Count relevant chunks (those that were retrieved)
            relevant_chunks = len(doc_chunks)  # All retrieved chunks are considered relevant
            
            chunk_info[doc] = {
                'total_chunks': total_chunks,
                'relevant_chunks': relevant_chunks
            }
        
        tracker = get_progress_tracker()
        tracker.update_stage("reading", 
                           f"Reading {len(relevant_documents)} documents",
                           "Extracting relevant information")
        tracker.update_reading_start(relevant_documents, chunk_info)
        
        # Get pre-computed query classification from shared store
        classification = shared.get("query_classification", {
            "query_type": "general",
            "confidence": 0.3,
            "reasoning": "No classification available, using general approach",
            "focus_areas": ["legal analysis", "case law", "precedents"],
            "response_sections": ["Direct Answer", "Legal Analysis", "Cases Referenced"]
        })
        
        # We'll read metadata directly from files during exec_async
        return [(doc, user_query, classification) for doc in relevant_documents]
    
    def _get_focused_extraction_prompt(self, user_query, classification, document_name, doc_content):
        """Generate a focused extraction prompt based on agent classification"""
        
        query_type = classification.get('query_type', 'general')
        focus_areas = classification.get('focus_areas', ['legal analysis'])
        response_sections = classification.get('response_sections', ['Direct Answer', 'Legal Analysis'])
        
        # Create dynamic focus areas text
        focus_text = "\n".join([f"- {area}" for area in focus_areas])
        
        # Create dynamic response format
        response_format = "\n".join([f"**{section}:** [Content for {section.lower()}]" for section in response_sections])
        response_format += "\n**Direct Quotes:** [Specific quotes with paragraph references]"
        
        return f"""You are a legal research assistant. Your task is to extract ONLY the information that directly answers the user's specific question from this legal case.

USER QUERY: {user_query}
LEGAL CASE: {document_name}
FULL CONTENT: {doc_content}

QUERY CLASSIFICATION: {classification.get('reasoning', 'General legal query')}

CRITICAL INSTRUCTIONS:
1. Focus ONLY on information that directly answers the user's query
2. Do not include irrelevant case details or background information
3. Be concise and targeted - lawyers need precise answers, not comprehensive case summaries
4. Include specific paragraph references and direct quotes where relevant
5. If the case doesn't address the query, clearly state that

FOCUS ON:
{focus_text}

RESPONSE FORMAT:
{response_format}

EXTRACTION:"""

    async def exec_async(self, doc_and_query):
        document_name, user_query, classification = doc_and_query
        
        # Update progress to show this document is being read
        tracker = get_progress_tracker()
        tracker.update_document_status(document_name, "reading")
        
        # Read the document and extract metadata in one operation
        config = get_system_config()
        doc_path = os.path.join(config.DOCUMENTS_DIR, document_name)
        
        if not os.path.exists(doc_path):
            logger.warning(f"Document not found: {document_name}")
            tracker.update_document_status(document_name, "error")
            return (document_name, f"Unable to read content for {document_name}", {})
        
        try:
            # Single file read and metadata extraction
            from utils.file_processor import create_file_processor
            processor = create_file_processor()
            file_info = processor.process_file(doc_path)
            doc_content = file_info.get('content', '')
            doc_metadata = file_info.get('metadata', {})
            
        except Exception as e:
            logger.error(f"Error reading {document_name}: {e}")
            tracker.update_document_status(document_name, "error")
            return (document_name, f"Error reading {document_name}: {str(e)}", {})
        
        # Use pre-computed query classification passed from prep_async
        logger.info(f"Reading {document_name} - Using pre-computed classification: '{classification.get('query_type')}' with confidence {classification.get('confidence', 0):.2f}")
        reading_prompt = self._get_focused_extraction_prompt(user_query, classification, document_name, doc_content)

        try:
            # Use async LLM call for true parallel execution
            response = await call_llm_async(reading_prompt)
            
            # Update progress to show this document is completed
            tracker.update_document_status(document_name, "completed")
            tracker.increment_reading(document_name)
            
            return (document_name, response, doc_metadata)
        except Exception as e:
            logger.error(f"Error in reading agent for {document_name}: {e}")
            
            # Update status to error
            tracker.update_document_status(document_name, "error")
            tracker.increment_reading(document_name)
            
            return (document_name, f"Error reading {document_name}: {str(e)}", doc_metadata)
    
    async def post_async(self, shared, prep_res, exec_res_list):
        document_summaries = {}
        document_metadata = {}
        
        for result in exec_res_list:
            if len(result) == 3:
                doc_name, summary, metadata = result
                document_summaries[doc_name] = summary
                document_metadata[doc_name] = metadata
            else:
                # Fallback for backward compatibility
                doc_name, summary = result
                document_summaries[doc_name] = summary
                document_metadata[doc_name] = {}
        
        shared["document_summaries"] = document_summaries
        shared["document_metadata"] = document_metadata
        
        logger.info(f"Reading completed for {len(document_summaries)} documents")
        return "default"

class AggregationAgentNode(Node):
    """Combine all information into final comprehensive response"""
    
    def _get_query_specific_aggregation_prompt(self, user_query, classification, all_summaries, available_citations, num_cases, language_instruction="Respond in clear, professional English."):
        """Generate a query-specific aggregation prompt based on agent classification"""
        
        query_type = classification.get('query_type', 'general')
        focus_areas = classification.get('focus_areas', ['legal analysis'])
        response_sections = classification.get('response_sections', ['Direct Answer', 'Legal Analysis'])
        reasoning = classification.get('reasoning', 'General legal query')
        
        # Create dynamic sections
        sections_text = ""
        for i, section in enumerate(response_sections):
            if i == 0:
                sections_text += f"\n## {section}\n\n[Provide a direct, concise answer to the user's question based on ALL {num_cases} cases]\n"
            else:
                sections_text += f"\n## {section}\n\n[Content for {section.lower()} synthesized from all relevant cases]\n"
        
        # Add cases referenced section
        sections_text += f"\n## Cases Referenced\n[List ALL {num_cases} cases with brief relevance to the query]\n"
        
        return f"""You are a senior legal research assistant providing a focused response to a specific legal query. Your response will be displayed in a web interface that supports markdown formatting.

🌐 LANGUAGE REQUIREMENT: {language_instruction}

USER QUERY: {user_query}

QUERY ANALYSIS: {reasoning}

RELEVANT LEGAL CASES AND SUMMARIES ({num_cases} cases found):
{all_summaries}

AVAILABLE CASE CITATIONS:
{available_citations}

CRITICAL INSTRUCTIONS - SYNTHESIS REQUIREMENT:
🚨 MANDATORY: You MUST analyze and synthesize information from ALL {num_cases} cases provided above
🚨 Do NOT focus on just one case - incorporate findings from EVERY relevant case
🚨 If multiple cases address the same issue, compare and contrast their approaches
🚨 If cases have different outcomes, explain the distinguishing factors

FORMATTING INSTRUCTIONS:
1. Answer ONLY what the user asked - do not provide unnecessary background or comprehensive case summaries
2. Be concise and directly responsive to the query
3. When citing cases, use ONLY the case citation format (e.g., "R. v. Smith, 2025 ONCJ 123") - do NOT include URLs
4. Do NOT use asterisks (*) around case names - write them as plain text
5. The frontend will automatically make case citations clickable
6. Ground ALL statements in the provided case law
7. If the cases don't address the query, clearly state that

FOCUS AREAS: {', '.join(focus_areas)}

SYNTHESIS APPROACH:
- STEP 1: Review EACH case individually and extract information relevant to the query
- STEP 2: Identify patterns, similarities, and differences across ALL cases
- STEP 3: Synthesize findings from ALL cases into a coherent response
- STEP 4: Ensure every relevant case is mentioned and its contribution explained

MANDATORY CASE-BY-CASE ANALYSIS:
Before writing your response, mentally go through each case and ask:
1. What does this case contribute to answering the user's query?
2. How does this case compare to the other cases?
3. Should this case be mentioned in my response?

RESPONSE STRUCTURE:
{sections_text}

RESPONSE:"""

    def prep(self, shared):
        user_query = shared.get("user_query", "")
        document_summaries = shared.get("document_summaries", {})
        document_metadata = shared.get("document_metadata", {})
        language_instruction = shared.get("language_instruction", "Respond in clear, professional English.")
        
        # Get pre-computed query classification from shared store
        classification = shared.get("query_classification", {
            "query_type": "general",
            "confidence": 0.3,
            "reasoning": "No classification available, using general approach",
            "focus_areas": ["legal analysis", "case law", "precedents"],
            "response_sections": ["Direct Answer", "Legal Analysis", "Cases Referenced"]
        })
        
        # Update progress to show aggregation stage is starting
        tracker = get_progress_tracker()
        tracker.update_aggregation()
        
        return (user_query, document_summaries, document_metadata, classification, language_instruction)
    
    def exec(self, prep_data):
        user_query, document_summaries, document_metadata, classification, language_instruction = prep_data
        
        tracker = get_progress_tracker()
        
        if not document_summaries:
            return "I apologize, but I could not find any relevant legal cases for your query. Please try rephrasing your question or providing more specific details."
        
        # Update progress to show we're building the response
        tracker.update_stage("aggregation", 
                           "Synthesizing findings", 
                           "Building targeted legal response")
        
        # Build case information with metadata
        case_info_list = []
        citation_map = {}  # Map citations to hyperlinks
        
        for doc_name, summary in document_summaries.items():
            metadata = document_metadata.get(doc_name, {})
            citation = metadata.get('citation', doc_name.replace('.txt', '').replace(' (CanLII)', ''))
            link = metadata.get('link', '')
            
            # Create hyperlink if available
            if link:
                hyperlink = f"[{citation}]({link})"
                citation_map[citation] = hyperlink
            else:
                citation_map[citation] = citation
            
            case_info_list.append({
                'doc_name': doc_name,
                'citation': citation,
                'link': link,
                'summary': summary,
                'hyperlink': citation_map[citation]
            })
        
        # Create the case summaries with hyperlinks
        all_summaries = "\n\n" + "="*50 + "\n\n".join([
            f"CASE: {case['hyperlink']}\nDOCUMENT FILE: {case['doc_name']}\nSUMMARY:\n{case['summary']}" 
            for case in case_info_list
        ])
        
        # Create list of available citations for the LLM (without showing URLs)
        available_citations = "\n".join([f"- {case['citation']}" for case in case_info_list])
        
        # Use pre-computed query classification passed from prep
        logger.info(f"Aggregation using pre-computed classification: {classification.get('query_type')} - {classification.get('reasoning', 'No reasoning')}")
        logger.info(f"Synthesizing information from {len(case_info_list)} cases: {[case['citation'] for case in case_info_list]}")
        
        aggregation_prompt = self._get_query_specific_aggregation_prompt(
            user_query, classification, all_summaries, available_citations, len(case_info_list), language_instruction
        )

        try:
            # Update progress to show we're calling the LLM
            tracker.update_stage("aggregation", 
                               "Synthesizing findings", 
                               "Generating comprehensive legal response")
            
            response = call_llm(aggregation_prompt)
            
            # Add a footer with quick access links
            footer = "\n\n---\n\n### 📑 Quick Case Access\n\n"
            for case in case_info_list:
                footer += f"- {case['hyperlink']}\n"
            
            response += footer
            return response
        except Exception as e:
            logger.error(f"Error in aggregation: {e}")
            return f"I apologize, but there was an error synthesizing the legal research results: {str(e)}"
    
    def post(self, shared, prep_res, exec_res):
        shared["final_response"] = exec_res
         
        tracker = get_progress_tracker()
        tracker.complete_session(True, "Legal research completed successfully")
        
        logger.info("Legal research process completed successfully")
        return "default"
 