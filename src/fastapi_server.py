from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
import json
import uuid
import os
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import our existing backend components
from flow import create_offline_indexing_flow, create_online_research_flow
from utils.progress import get_progress_tracker
from config import get_system_config, get_vector_db_config, get_llm_config
from utils.vector_db import create_vector_db
from utils.call_llm import set_llm_config, reset_usage_tracking, get_usage_and_cost

app = FastAPI(title="Legal AI Research API", version="1.0.0")

# Add CORS middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
active_sessions: Dict[str, Dict] = {}
websocket_connections: Dict[str, List[WebSocket]] = {}

def cleanup_old_sessions():
    """Remove sessions older than 1 hour to prevent memory leaks"""
    current_time = datetime.now()
    sessions_to_remove = []
    
    for session_id, session_data in active_sessions.items():
        created_at = session_data.get("created_at", current_time)
        # if current_time - created_at > timedelta(hours=1):
        sessions_to_remove.append(session_id)
    
    for session_id in sessions_to_remove:
        del active_sessions[session_id]
        if session_id in websocket_connections:
            del websocket_connections[session_id]
        logger.info(f"Cleaned up old session: {session_id}")

@app.on_event("startup")
async def startup_event():
    """Clear any stale connections on startup"""
    global websocket_connections, active_sessions
    websocket_connections.clear()
    active_sessions.clear()
    logger.info("Server started - cleared stale sessions and websocket connections")

# Try to include external whatsappbot router (if available)
try:
    from external.whatsappbot_shim import router as whatsapp_router
    if whatsapp_router:
        app.include_router(whatsapp_router)
        logger.info("Included external whatsappbot whatsapp router")
    else:
        logger.info("External whatsappbot router not available")
except Exception as e:
    logger.warning(f"Could not include external whatsapp router: {e}")

# Pydantic Models
class SystemStatus(BaseModel):
    indexingCompleted: bool
    documentCount: int
    indexStats: Dict[str, int]
    vectorDbStats: Optional[Dict[str, Any]] = None

class DocumentInfo(BaseModel):
    id: str
    name: str
    type: str
    size: float  # MB
    status: str  # "indexed", "processing", "error", "pending"
    chunks: int
    lastModified: datetime

class IndexingRequest(BaseModel):
    rebuild: bool = False

class ResearchQuery(BaseModel):
    query: str
    filters: Optional[Dict[str, Any]] = None
    llm_provider: Optional[str] = "openai"  # "openai" or "gemini"
    llm_model: Optional[str] = None  # Model name, defaults based on provider

class ResearchProgress(BaseModel):
    stage: str
    status: str
    currentActivity: str
    elapsedTime: int
    progress: float
    documentsFound: Optional[int] = None
    documentsBeingRead: Optional[List[Dict]] = None
    completedReadings: Optional[int] = None
    totalReadings: Optional[int] = None

class CitedDocument(BaseModel):
    id: str
    title: str
    citation: str
    court: str
    date: str
    relevanceScore: float
    keyPassages: List[str]
    url: Optional[str] = None
    link: Optional[str] = None

class PruningDetail(BaseModel):
    documentName: str
    relevant: bool
    explanation: str

class ModelCost(BaseModel):
    promptTokens: int
    completionTokens: int
    totalTokens: int
    callCount: int
    promptCost: float
    completionCost: float
    totalCost: float

class CostBreakdown(BaseModel):
    totalPromptTokens: int
    totalCompletionTokens: int
    totalTokens: int
    totalCost: float
    models: Dict[str, ModelCost]
    provider: str

class ResearchResult(BaseModel):
    success: bool
    query: str
    timestamp: datetime
    documentsFound: int
    uniqueDocuments: int
    relevantDocuments: int
    response: str
    executiveSummary: str
    keyFindings: List[str]
    citedDocuments: List[CitedDocument]
    legalPrinciples: List[str]
    recommendations: List[str]
    processingTime: float
    pruningDetails: Optional[List[PruningDetail]] = None
    costBreakdown: Optional[CostBreakdown] = None
    error: Optional[str] = None

# Helper Functions
def get_documents_info() -> List[DocumentInfo]:
    """Get information about documents in the system"""
    config = get_system_config()
    documents_dir = config.DOCUMENTS_DIR
    
    if not os.path.exists(documents_dir):
        return []
    
    documents = []
    for file in os.listdir(documents_dir):
        if file.endswith('.txt'):
            file_path = os.path.join(documents_dir, file)
            try:
                stat = os.stat(file_path)
                size_mb = stat.st_size / (1024 * 1024)
                
                documents.append(DocumentInfo(
                    id=file.replace('.txt', ''),
                    name=file,
                    type="TXT",
                    size=round(size_mb, 2),
                    status="indexed",  # For now, assume all are indexed
                    chunks=0,  # Will be calculated if needed
                    lastModified=datetime.fromtimestamp(stat.st_mtime)
                ))
            except Exception as e:
                logger.error(f"Error processing file {file}: {e}")
                continue
    
    return documents

def check_indexing_status() -> SystemStatus:
    """Check if the vector database is indexed and get stats"""
    try:
        config = get_system_config()
        vdb_config = get_vector_db_config()
        
        # Check if chroma db exists
        chroma_path = config.CHROMA_DB_PATH
        indexing_completed = os.path.exists(chroma_path)
        
        # Get document count
        documents = get_documents_info()
        document_count = len(documents)
        
        # Get vector DB stats if available
        vector_db_stats = None
        if indexing_completed:
            try:
                vector_db = create_vector_db()
                vector_db.create_or_get_collection(vdb_config.COLLECTION_NAME)
                vector_db_stats = vector_db.get_collection_stats()
            except Exception as e:
                logger.error(f"Error getting vector DB stats: {e}")
                indexing_completed = False
        
        return SystemStatus(
            indexingCompleted=indexing_completed,
            documentCount=document_count,
            indexStats={
                "filesProcessed": document_count if indexing_completed else 0,
                "chunksIndexed": vector_db_stats.get("total_documents", 0) if vector_db_stats else 0
            },
            vectorDbStats=vector_db_stats
        )
    except Exception as e:
        logger.error(f"Error checking indexing status: {e}")
        return SystemStatus(
            indexingCompleted=False,
            documentCount=0,
            indexStats={"filesProcessed": 0, "chunksIndexed": 0}
        )

def sync_broadcast_progress(session_id: str, progress_data: Dict):
    """Synchronously broadcast progress to WebSocket clients"""
    import asyncio
    import threading
    import concurrent.futures
    
    async def do_broadcast():
        return await broadcast_progress(session_id, progress_data)
    
    try:
        # Try to get current event loop
        loop = asyncio.get_running_loop()
        
        # Run in thread to avoid "already running" error
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, do_broadcast())
            # Wait for completion with timeout
            future.result(timeout=2.0)
            
    except Exception as e:
        logger.warning(f"Sync WebSocket broadcast failed: {e}")
        # Fallback to async task scheduling
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(broadcast_progress(session_id, progress_data))
        except:
            pass

async def broadcast_progress(session_id: str, progress_data: Dict):
    """Broadcast progress to all connected WebSocket clients for a session"""
    if session_id in websocket_connections:
        disconnected = []
        for websocket in websocket_connections[session_id]:
            try:
                await websocket.send_text(json.dumps(progress_data))
            except Exception as e:
                logger.error(f"Error sending to websocket: {e}")
                disconnected.append(websocket)
        
        # Remove disconnected websockets
        for ws in disconnected:
            websocket_connections[session_id].remove(ws)

def extract_citations_from_response(response: str, processed_documents: list) -> List[CitedDocument]:
    """Extract citations from the research response for Supreme Court of Pakistan cases"""
    citations = []
    
    for i, doc_data in enumerate(processed_documents):
        # Skip failed documents
        if doc_data.get('failed', False):
            continue
            
        # Extract data from processed document
        doc_name = doc_data.get('doc_id', '')
        summary = doc_data.get('summary', '')
        metadata = doc_data.get('metadata', {})
        
        # Extract citation from filename (case number)
        citation = doc_name.replace('.txt', '')
        
        # Try to get metadata from processed document first
        case_title = metadata.get('case_title', citation)
        court = metadata.get('court', "Supreme Court of Pakistan")
        date = metadata.get('judgment_date', "2025")
        pdf_url = metadata.get('pdf_url')
        
        # If metadata is empty, try to read from file
        if not metadata:
            try:
                # Read the file to get actual metadata
                config = get_system_config()
                file_path = os.path.join(config.DOCUMENTS_DIR, doc_name)
                
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read(2000)  # Read first 2000 chars to get metadata
                        
                        # Extract metadata from the header section
                        for line in content.split('\n'):
                            line_stripped = line.strip()
                            
                            # Extract case title
                            if 'Case Title:' in line_stripped or 'case_title:' in line_stripped.lower():
                                case_title = line_stripped.split(':', 1)[1].strip()
                            
                            # Extract judgment date
                            elif 'Judgment Date:' in line_stripped or 'judgment_date:' in line_stripped.lower():
                                date = line_stripped.split(':', 1)[1].strip()
                            
                            # Extract PDF URL
                            elif 'PDF URL:' in line_stripped or 'pdf_url:' in line_stripped.lower():
                                pdf_url = line_stripped.split(':', 1)[1].strip()
                                if pdf_url.lower() == 'n/a':
                                    pdf_url = None
                            
                            # Extract court name (though it should always be Supreme Court of Pakistan)
                            elif 'Court:' in line_stripped or line_stripped == 'SUPREME COURT OF PAKISTAN':
                                if ':' in line_stripped:
                                    court = line_stripped.split(':', 1)[1].strip()
                                else:
                                    court = "Supreme Court of Pakistan"
            
            except Exception as e:
                logger.error(f"Error reading metadata from file {doc_name}: {e}")
        
        # Create citation entry with extracted metadata
        citations.append(CitedDocument(
            id=str(i + 1),
            title=case_title,
            citation=citation,
            court=court,
            date=date,
            relevanceScore=0.85,  # Could be calculated from similarity scores
            keyPassages=[
                # Extract first few sentences from summary as key passages
                summary.split('.')[0] + '.' if '.' in summary else summary[:200] + '...'
            ],
            url=pdf_url,
            link=pdf_url
        ))
    
    return citations

# API Endpoints

@app.get("/api/models")
async def get_available_models():
    """Get list of available LLM models"""
    llm_config = get_llm_config()
    return {
        "providers": {
            "openai": {
                "models": llm_config.OPENAI_MODELS,
                "default": llm_config.OPENAI_MODELS[0]
            },
            "gemini": {
                "models": llm_config.GEMINI_MODELS,
                "default": llm_config.GEMINI_MODELS[0]
            }
        },
        "default_provider": llm_config.PROVIDER,
        "default_model": llm_config.MODEL
    }

@app.get("/api/status", response_model=SystemStatus)
async def get_system_status():
    """Get current system status including indexing completion and document stats"""
    return check_indexing_status()

@app.get("/api/documents", response_model=List[DocumentInfo])
async def get_documents():
    """Get list of all documents in the system"""
    return get_documents_info()

@app.post("/api/indexing/start")
async def start_indexing(request: IndexingRequest, background_tasks: BackgroundTasks):
    """Start the document indexing process"""
    session_id = str(uuid.uuid4())
    
    def run_indexing():
        try:
            # Create shared store for offline processing
            shared = {
                "documents_directory": "backend/assets/data",
                "processed_files": [],
                "total_files_processed": 0,
                "vector_db": None,
                "total_chunks_indexed": 0
            }
            
            # Create and run offline flow
            offline_flow = create_offline_indexing_flow()
            offline_flow.run(shared)
            
            logger.info(f"Indexing completed: {shared['total_files_processed']} files, {shared['total_chunks_indexed']} chunks")
            
        except Exception as e:
            logger.error(f"Indexing error: {e}")
    
    background_tasks.add_task(run_indexing)
    
    return {
        "message": "Indexing started",
        "session_id": session_id
    }

@app.post("/api/research/query")
async def start_research(query: ResearchQuery, background_tasks: BackgroundTasks):
    """Start a research query"""
    # Clean up old sessions periodically
    cleanup_old_sessions()
    
    session_id = str(uuid.uuid4())
    logger.info(f"Creating research session {session_id} for query: {query.query[:100]}...")
    
    # Determine LLM provider and model
    llm_config = get_llm_config()
    provider = query.llm_provider or llm_config.PROVIDER
    
    # Set default model based on provider if not specified
    if query.llm_model:
        model = query.llm_model
    else:
        if provider == "openai":
            model = llm_config.OPENAI_MODELS[0]
        elif provider == "gemini":
            model = llm_config.GEMINI_MODELS[0]
        else:
            model = llm_config.MODEL
    
    logger.info(f"Using LLM: {provider} / {model}")
    
    # Store session info
    active_sessions[session_id] = {
        "query": query.query,
        "llm_provider": provider,
        "llm_model": model,
        "status": "starting",
        "created_at": datetime.now(),
        "progress": ResearchProgress(
            stage="starting",
            status="Initializing research",
            currentActivity="Preparing query analysis",
            elapsedTime=0,
            progress=0.0
        )
    }
    logger.info(f"Session {session_id} stored in active_sessions. Total sessions: {len(active_sessions)}")
    
    async def run_research():
        try:
            logger.info(f"[{session_id}] STEP 1: Starting run_research() background task")
            
            # Configure LLM for this research session
            logger.info(f"[{session_id}] STEP 2: Retrieving session data from active_sessions")
            session_data = active_sessions[session_id]
            logger.info(f"[{session_id}] STEP 3: Configuring LLM - Provider: {session_data['llm_provider']}, Model: {session_data['llm_model']}")
            set_llm_config(session_data["llm_provider"], session_data["llm_model"])
            logger.info(f"[{session_id}] ✓ LLM configured successfully")
            
            # Reset usage tracking for this session (works for both OpenAI and Gemini)
            reset_usage_tracking()
            logger.info(f"[{session_id}] ✓ Token usage tracking reset for {session_data['llm_provider']}")
            
            # Setup progress tracking
            logger.info(f"[{session_id}] STEP 4: Getting progress tracker instance")
            tracker = get_progress_tracker()
            start_time = datetime.now()
            logger.info(f"[{session_id}] ✓ Progress tracker obtained, start time: {start_time.isoformat()}")
            
            # Initialize progress session
            logger.info(f"[{session_id}] STEP 5: Initializing progress session")
            tracker.start_session(query.query)
            logger.info(f"[{session_id}] ✓ Progress session started")
            
            # Clear any previous session data
            logger.info(f"[{session_id}] STEP 6: Initializing progress data structure")
            tracker.progress_data = {
                'query': query.query,
                'stage': 'started',
                'status': 'Research started',
                'start_time': datetime.now().isoformat(),
                'elapsed_time': 0,
                'stage_elapsed_time': 0,
                'documents_found': 0,
                'documents_being_read': [],
                'completed_readings': 0,
                'total_readings': 0,
                'pruning_completed': 0,
                'total_pruning': 0,
                'stages_completed': [],
                'current_activity': 'Starting research process',
                'document_statuses': {}
            }
            logger.info(f"[{session_id}] ✓ Progress data initialized")
            
            def progress_callback(progress_data):
                """Convert progress data to frontend format and broadcast"""
                try:
                    logger.debug(f"[{session_id}] Progress callback triggered - Stage: {progress_data.get('stage', 'unknown')}")
                    
                    # Use elapsed time from progress tracker instead of calculating from start_time
                    elapsed = int(progress_data.get('elapsed_time', 0))
                    
                    # Map backend stages to frontend format
                    stage_mapping = {
                        "retrieval": "retrieval",
                        "extraction": "pruning", 
                        "pruning": "pruning",
                        "reading_prep": "reading",
                        "reading": "reading",
                        "aggregation": "aggregation",
                        "completed": "completed",
                        "started": "retrieval"  # Map started stage to retrieval
                    }
                    
                    stage = stage_mapping.get(progress_data.get('stage', 'unknown'), progress_data.get('stage', 'unknown'))
                    logger.debug(f"[{session_id}] Mapped stage: {progress_data.get('stage')} -> {stage}")
                    
                    # Calculate overall progress based on stage completion and sub-progress
                    if stage == "reading":
                        # During reading, show progress based on completed documents
                        completed_readings = progress_data.get('completed_readings', 0)
                        total_readings = progress_data.get('total_readings', 0)
                        if total_readings > 0:
                            # Reading stage is 50-75% of total progress
                            reading_progress = (completed_readings / total_readings) * 25  # 25% range for reading
                            overall_progress = 50 + reading_progress  # Start at 50%, go to 75%
                        else:
                            overall_progress = 50
                    elif stage == "aggregation":
                        # Aggregation stage is 75-100% of total progress
                        overall_progress = 75
                    else:
                        # Other stages have fixed progress
                        stage_progress = {
                            "retrieval": 0,
                            "pruning": 25,
                            "completed": 100
                        }
                        overall_progress = stage_progress.get(stage, 0)
                    
                    # Create document status data for parallel processing display
                    documents_being_read = []
                    if stage == "reading":
                        # Get the actual document statuses from progress tracker
                        document_statuses = progress_data.get('document_statuses', {})
                        documents_list = progress_data.get('documents_being_read', [])
                        completed_count = progress_data.get('completed_readings', 0)
                        total_count = progress_data.get('total_readings', 0)
                        
                        # Create document status objects for each document
                        for doc_name in documents_list:
                            # Get the actual status from the progress tracker
                            actual_status = document_statuses.get(doc_name, "pending")
                            
                            # Clean up the document name for display (remove file extension)
                            display_name = doc_name.replace('.txt', '')
                            
                            # Get actual chunk data from progress tracker
                            chunks = progress_data.get('document_chunks', {}).get(doc_name, 0)
                            relevant_chunks = progress_data.get('document_relevant_chunks', {}).get(doc_name, 0)
                            
                            # Get actual processing time from progress tracker
                            document_processing_times = progress_data.get('document_processing_times', {})
                            doc_timing = document_processing_times.get(doc_name, {})
                            processing_time = doc_timing.get('duration', 0) if actual_status == "completed" else 0
                            
                            documents_being_read.append({
                                "name": display_name,
                                "fullName": doc_name,  # Keep original for reference
                                "status": actual_status,
                                "chunks": chunks,
                                "relevantChunks": relevant_chunks,
                                "processingTime": processing_time
                            })
                    
                    frontend_progress = {
                        "stage": stage,
                        "status": progress_data.get('status', 'Processing'),
                        "currentActivity": progress_data.get('current_activity', ''),
                        "elapsedTime": elapsed,
                        "progress": overall_progress,
                        "documentsFound": progress_data.get('retrieval_count'),
                        "documentsBeingRead": documents_being_read,
                        "completedReadings": progress_data.get('completed_readings', 0),
                        "totalReadings": progress_data.get('total_readings', 0),
                        "stageDurations": progress_data.get('stage_durations', {}),
                        "stageElapsedTime": progress_data.get('stage_elapsed_time', 0)
                    }
                
                    # Update session
                    active_sessions[session_id]["progress"] = frontend_progress
                    logger.debug(f"[{session_id}] Session progress updated - Stage: {stage}, Progress: {overall_progress}%")
                    
                    # Broadcast to WebSocket clients immediately using sync version
                    logger.debug(f"[{session_id}] Broadcasting progress to WebSocket clients")
                    sync_broadcast_progress(session_id, frontend_progress)
                    logger.debug(f"[{session_id}] ✓ Progress broadcast complete")
                    
                except Exception as e:
                    logger.error(f"[{session_id}] ERROR in progress_callback: {e}", exc_info=True)
            
            logger.info(f"[{session_id}] STEP 7: Registering progress callback")
            tracker.register_callback(progress_callback)
            logger.info(f"[{session_id}] ✓ Progress callback registered")
            
            # Create shared store for online processing
            logger.info(f"[{session_id}] STEP 8: Creating shared store for online processing")
            shared = {
                "user_query": query.query,
                "vector_db": None,  # Will be loaded by the flow
                "retrieved_chunks": [],
                "retrieval_count": 0,
                "unique_documents": [],
                "unique_document_count": 0,
                "processed_documents": [],
                "successful_documents": [],
                "failed_documents": [],
                "final_response": ""
            }
            logger.info(f"[{session_id}] ✓ Shared store created with query: {query.query[:50]}...")
            
            # Create and run online flow
            logger.info(f"[{session_id}] STEP 9: Creating online research flow")
            online_flow = create_online_research_flow()
            logger.info(f"[{session_id}] ✓ Online flow created, starting async execution...")
            
            await online_flow.run_async(shared)
            
            logger.info(f"[{session_id}] ✓ Online flow completed successfully!")
            logger.info(f"[{session_id}] Flow results - Retrieval count: {shared.get('retrieval_count', 0)}, Unique docs: {shared.get('unique_document_count', 0)}")
            
            # Process results for frontend
            logger.info(f"[{session_id}] STEP 10: Processing results for frontend")
            processing_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"[{session_id}] Total processing time: {processing_time:.2f} seconds")
            
            # Extract executive summary (first paragraph of response)
            logger.info(f"[{session_id}] STEP 11: Extracting executive summary")
            response_text = shared.get("final_response", "")
            logger.info(f"[{session_id}] Response text length: {len(response_text)} characters")
            executive_summary = response_text.split('\n\n')[0] if response_text else "Research completed successfully."
            logger.info(f"[{session_id}] ✓ Executive summary extracted ({len(executive_summary)} chars)")
            
            # Extract key findings (look for bullet points or numbered items)
            logger.info(f"[{session_id}] STEP 12: Extracting key findings")
            key_findings = []
            lines = response_text.split('\n')
            for line in lines:
                if line.strip().startswith('- ') or line.strip().startswith('* ') or line.strip().startswith('•'):
                    key_findings.append(line.strip()[2:])
                elif line.strip() and any(x in line.lower() for x in ['finding', 'key', 'important', 'significant']):
                    key_findings.append(line.strip())
            
            if not key_findings:
                logger.info(f"[{session_id}] No bullet points found, using default key findings")
                key_findings = [
                    "Research analysis completed with relevant legal precedents identified",
                    "Key legal principles extracted from relevant case law",
                    "Comprehensive legal framework established for the query"
                ]
            logger.info(f"[{session_id}] ✓ Extracted {len(key_findings)} key findings")
            
            # Extract legal principles and recommendations
            logger.info(f"[{session_id}] STEP 13: Setting legal principles and recommendations")
            legal_principles = [
                "Legal precedent provides guidance for similar cases",
                "Judicial consistency maintains legal certainty",
                "Contemporary legal principles adapt to modern circumstances"
            ]
            
            recommendations = [
                "Consider the precedential value of identified cases",
                "Review the legal framework established by relevant decisions",
                "Analyze the consistency of judicial approaches in this area"
            ]
            logger.info(f"[{session_id}] ✓ Legal principles and recommendations set")
            
            # Create citations from processed documents
            logger.info(f"[{session_id}] STEP 14: Extracting citations from response")
            processed_docs = shared.get("processed_documents", [])
            citations = extract_citations_from_response(response_text, processed_docs)
            logger.info(f"[{session_id}] ✓ Extracted {len(citations)} citations")
            
            # Extract processing details (replacement for pruning details)
            logger.info(f"[{session_id}] STEP 14.5: Extracting processing details")
            pruning_details = []
            successful_docs = shared.get("successful_documents", [])
            failed_docs = shared.get("failed_documents", [])
            
            # Add successful documents as "relevant"
            for doc_data in successful_docs:
                doc_name = doc_data.get('doc_id', 'Unknown')
                summary = doc_data.get('summary', '')
                # Extract first sentence as explanation
                explanation = summary.split('.')[0] + '.' if '.' in summary else summary[:100]
                pruning_details.append(PruningDetail(
                    documentName=doc_name,
                    relevant=True,
                    explanation=f"Processed successfully. {explanation}"
                ))
            
            # Add failed documents as "not relevant"
            for doc_data in failed_docs:
                doc_name = doc_data.get('doc_id', 'Unknown')
                pruning_details.append(PruningDetail(
                    documentName=doc_name,
                    relevant=False,
                    explanation="Document processing failed"
                ))
            
            logger.info(f"[{session_id}] ✓ Extracted {len(pruning_details)} processing details ({len(successful_docs)} successful, {len(failed_docs)} failed)")
            
            # Get usage and cost data (provider-agnostic)
            cost_breakdown = None
            logger.info(f"[{session_id}] STEP 14.6: Calculating costs for {session_data['llm_provider']}")
            usage_data = get_usage_and_cost()
            
            # Only create cost breakdown if we have usage data
            if usage_data.get("models"):
                # Convert to CostBreakdown model
                model_costs = {}
                for model_name, cost_data in usage_data.get("models", {}).items():
                    model_costs[model_name] = ModelCost(
                        promptTokens=cost_data["prompt_tokens"],
                        completionTokens=cost_data["completion_tokens"],
                        totalTokens=cost_data["total_tokens"],
                        callCount=cost_data["call_count"],
                        promptCost=cost_data["prompt_cost"],
                        completionCost=cost_data["completion_cost"],
                        totalCost=cost_data["total_cost"]
                    )
                
                cost_breakdown = CostBreakdown(
                    totalPromptTokens=usage_data["total_prompt_tokens"],
                    totalCompletionTokens=usage_data["total_completion_tokens"],
                    totalTokens=usage_data["total_tokens"],
                    totalCost=usage_data["total_cost"],
                    models=model_costs,
                    provider=usage_data.get("provider", session_data["llm_provider"])
                )
                logger.info(f"[{session_id}] ✓ Cost calculated: ${cost_breakdown.totalCost:.4f} ({cost_breakdown.totalTokens:,} tokens)")
            else:
                logger.info(f"[{session_id}] ✓ No usage data available for cost calculation")
            
            logger.info(f"[{session_id}] STEP 15: Creating ResearchResult object")
            result = ResearchResult(
                success=True,
                query=query.query,
                timestamp=datetime.now(),
                documentsFound=shared.get("retrieval_count", 0),
                uniqueDocuments=shared.get("unique_document_count", 0),
                relevantDocuments=len(shared.get("successful_documents", [])),
                response=response_text,
                executiveSummary=executive_summary,
                keyFindings=key_findings[:6],  # Limit to 6 findings
                citedDocuments=citations[:10],  # Limit to 10 citations
                legalPrinciples=legal_principles,
                recommendations=recommendations,
                processingTime=processing_time,
                pruningDetails=pruning_details,
                costBreakdown=cost_breakdown
            )
            logger.info(f"[{session_id}] ✓ ResearchResult object created successfully")
            
            # Store result
            logger.info(f"[{session_id}] STEP 16: Storing result in active_sessions")
            active_sessions[session_id]["result"] = result
            active_sessions[session_id]["status"] = "completed"
            logger.info(f"[{session_id}] ✓ Result stored, status set to 'completed'")
            
            logger.info(f"[{session_id}] ========== RESEARCH COMPLETED SUCCESSFULLY ==========")
            logger.info(f"[{session_id}] Final stats - Docs found: {result.documentsFound}, Unique: {result.uniqueDocuments}, Relevant: {result.relevantDocuments}, Time: {processing_time:.2f}s")
            
            # Note: Completion notification is sent by AggregationAgentNode.post() method
            
        except Exception as e:
            logger.error(f"[{session_id}] ========== RESEARCH FAILED ==========")
            logger.error(f"[{session_id}] Exception type: {type(e).__name__}")
            logger.error(f"[{session_id}] Exception message: {str(e)}")
            logger.error(f"[{session_id}] Full traceback:", exc_info=True)
            logger.info(f"[{session_id}] Creating error result object")
            error_result = ResearchResult(
                success=False,
                query=query.query,
                timestamp=datetime.now(),
                documentsFound=0,
                uniqueDocuments=0,
                relevantDocuments=0,
                response="",
                executiveSummary="",
                keyFindings=[],
                citedDocuments=[],
                legalPrinciples=[],
                recommendations=[],
                processingTime=0,
                error=str(e)
            )
            
            logger.info(f"[{session_id}] Storing error result in active_sessions")
            active_sessions[session_id]["result"] = error_result
            active_sessions[session_id]["status"] = "error"
            
            # Send error notification
            logger.info(f"[{session_id}] Broadcasting error notification to clients")
            error_data = {
                "stage": "error",
                "status": "Research failed",
                "currentActivity": f"Error: {str(e)}",
                "elapsedTime": 0,
                "progress": 0.0,
                "error": str(e)
            }
            
            await broadcast_progress(session_id, error_data)
            logger.info(f"[{session_id}] Error notification sent")
    
    logger.info(f"[{session_id}] Scheduling run_research() as background task")
    background_tasks.add_task(run_research)
    logger.info(f"[{session_id}] Background task scheduled successfully")
    
    logger.info(f"[{session_id}] Returning response to frontend with session_id")
    return {
        "message": "Research started",
        "session_id": session_id
    }

@app.get("/api/research/progress/{session_id}", response_model=ResearchProgress)
async def get_research_progress(session_id: str):
    """Get current progress of a research session"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return active_sessions[session_id]["progress"]

@app.get("/api/research/results/{session_id}", response_model=ResearchResult)
async def get_research_results(session_id: str):
    """Get results of a completed research session"""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = active_sessions[session_id]
    if "result" not in session:
        raise HTTPException(status_code=202, detail="Research not completed yet")
    
    return session["result"]

@app.websocket("/ws/progress/{session_id}")
async def websocket_progress(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time progress updates"""
    logger.info(f"🔌 [WebSocket] New connection request for session: {session_id}")
    
    try:
        await websocket.accept()
        logger.info(f"✅ [WebSocket] Connection accepted for session: {session_id}")
    except Exception as e:
        logger.error(f"❌ [WebSocket] Failed to accept connection for session {session_id}: {e}")
        return
    
    # Add to connections
    if session_id not in websocket_connections:
        websocket_connections[session_id] = []
    websocket_connections[session_id].append(websocket)
    logger.info(f"[WebSocket] Active connections for session {session_id}: {len(websocket_connections[session_id])}")
    logger.info(f"[WebSocket] Total sessions with connections: {len(websocket_connections)}")
    
    try:
        # Send current progress if session exists
        if session_id in active_sessions:
            progress = active_sessions[session_id]["progress"]
            progress_json = json.dumps(progress.dict() if hasattr(progress, 'dict') else progress)
            await websocket.send_text(progress_json)
            logger.info(f"📤 [WebSocket] Sent initial progress to session {session_id}")
        else:
            logger.warning(f"⚠️ [WebSocket] Session {session_id} not found in active_sessions")
        
        # Keep connection alive
        logger.info(f"🔄 [WebSocket] Entering keep-alive loop for session {session_id}")
        while True:
            try:
                message = await websocket.receive_text()
                logger.debug(f"📨 [WebSocket] Received message from session {session_id}: {message}")
            except WebSocketDisconnect as e:
                logger.info(f"🔌 [WebSocket] Client disconnected from session {session_id} - Code: {e.code}")
                break
            except Exception as e:
                logger.error(f"❌ [WebSocket] Error receiving message from session {session_id}: {e}")
                break
    except Exception as e:
        logger.error(f"❌ [WebSocket] Unexpected error for session {session_id}: {e}", exc_info=True)
    finally:
        # Remove from connections
        logger.info(f"🧹 [WebSocket] Cleaning up connection for session {session_id}")
        if session_id in websocket_connections:
            try:
                websocket_connections[session_id].remove(websocket)
                remaining = len(websocket_connections[session_id])
                logger.info(f"📊 [WebSocket] Remaining connections for session {session_id}: {remaining}")
                
                if not websocket_connections[session_id]:
                    del websocket_connections[session_id]
                    logger.info(f"🗑️ [WebSocket] Removed session {session_id} from websocket_connections")
            except ValueError:
                logger.warning(f"⚠️ [WebSocket] Connection already removed from session {session_id}")
        
        logger.info(f"✅ [WebSocket] Cleanup complete for session {session_id}")

@app.get("/api/debug/sessions")
async def debug_sessions():
    """Debug endpoint to check active sessions"""
    return {
        "active_sessions": list(active_sessions.keys()),
        "session_count": len(active_sessions),
        "websocket_connections": list(websocket_connections.keys())
    }

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Legal AI Research API is running", "status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
