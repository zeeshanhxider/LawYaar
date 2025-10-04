import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import threading
import logging

logger = logging.getLogger(__name__)

class ProgressTracker:
    def __init__(self):
        self.current_stage = "idle"
        self.progress_data = {}
        self.start_time = None
        self.stage_start_time = None
        self.stage_durations = {}  # Track duration of each completed stage
        self.document_processing_times = {}  # Track processing time for each document
        self.callbacks = []
        self._lock = threading.Lock()
        
    def register_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """
        Register a callback function to be called on progress updates
        
        Args:
            callback: Function that takes progress data as argument
        """
        with self._lock:
            self.callbacks.append(callback)
        logger.info("Registered progress callback")
    
    def start_session(self, query: str):
        """
        Start a new progress tracking session
        
        Args:
            query: The user query being processed
        """
        with self._lock:
            self.start_time = time.time()
            self.stage_start_time = time.time()
            self.current_stage = "started"
            self.progress_data = {
                'query': query,
                'stage': self.current_stage,
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
                'current_activity': 'Starting research process'
            }
            
        self._notify_callbacks()
        logger.info(f"Started progress session for query: {query[:50]}...")
    
    def update_stage(self, stage: str, status: str, activity: str = ""):
        """
        Update the current stage
        
        Args:
            stage: Name of the current stage
            status: Status message for the stage
            activity: Current activity description
        """
        with self._lock:
            current_time = time.time()
            
            if self.current_stage != "idle" and self.stage_start_time:
                # Calculate and store duration of previous stage
                previous_stage_duration = current_time - self.stage_start_time
                self.stage_durations[self.current_stage] = previous_stage_duration
                
                # Mark previous stage as completed
                if self.current_stage not in self.progress_data.get('stages_completed', []):
                    self.progress_data.setdefault('stages_completed', []).append(self.current_stage)
            
            self.current_stage = stage
            self.stage_start_time = current_time
            
            self.progress_data.update({
                'stage': stage,
                'status': status,
                'stage_elapsed_time': 0,
                'current_activity': activity or status,
                'stage_durations': self.stage_durations.copy()
            })
            
            if self.start_time:
                self.progress_data['elapsed_time'] = current_time - self.start_time
        
        self._notify_callbacks()
        logger.info(f"Stage updated: {stage} - {status}")
    
    def update_retrieval(self, documents_found: int):
        """
        Update retrieval progress
        
        Args:
            documents_found: Number of documents found
        """
        with self._lock:
            self.progress_data.update({
                'documents_found': documents_found,
                'current_activity': f'Found {documents_found} relevant documents'
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Retrieval updated: {documents_found} documents found")
    
    def update_pruning(self, completed: int, total: int):
        """
        Update pruning progress
        
        Args:
            completed: Number of completed pruning operations
            total: Total number of pruning operations
        """
        with self._lock:
            self.progress_data.update({
                'pruning_completed': completed,
                'total_pruning': total,
                'current_activity': f'Pruning documents: {completed}/{total} completed'
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Pruning progress: {completed}/{total}")
    
    def increment_pruning(self, total: int):
        """
        Increment pruning progress by one (thread-safe)
        
        Args:
            total: Total number of pruning operations
        """
        with self._lock:
            current_completed = self.progress_data.get('pruning_completed', 0)
            new_completed = current_completed + 1
            self.progress_data.update({
                'pruning_completed': new_completed,
                'total_pruning': total,
                'current_activity': f'Pruning documents: {new_completed}/{total} completed'
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Pruning progress incremented: {new_completed}/{total}")
    
    def update_reading_start(self, documents: List[str], chunk_info: Dict[str, Dict] = None):
        """
        Update when reading stage starts
        
        Args:
            documents: List of document names being read
            chunk_info: Optional dict with chunk information for each document
        """
        with self._lock:
            # Initialize document statuses
            document_statuses = {doc: "pending" for doc in documents}
            
            # Initialize chunk information if provided
            document_chunks = {}
            document_relevant_chunks = {}
            if chunk_info:
                for doc in documents:
                    doc_chunk_info = chunk_info.get(doc, {})
                    document_chunks[doc] = doc_chunk_info.get('total_chunks', 0)
                    document_relevant_chunks[doc] = doc_chunk_info.get('relevant_chunks', 0)
            
            self.progress_data.update({
                'documents_being_read': documents.copy(),
                'document_statuses': document_statuses,
                'total_readings': len(documents),
                'completed_readings': 0,
                'current_activity': f'Reading {len(documents)} relevant documents',
                'document_chunks': document_chunks,
                'document_relevant_chunks': document_relevant_chunks
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Reading started: {len(documents)} documents")
    
    def update_reading_progress(self, document_name: str, completed_count: int):
        """
        Update progress of document reading
        
        Args:
            document_name: Name of the document being read
            completed_count: Number of completed readings
        """
        with self._lock:
            self.progress_data.update({
                'completed_readings': completed_count,
                'current_activity': f'Reading {document_name}' if document_name else f'Reading completed: {completed_count} documents'
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Reading progress: {document_name} ({completed_count}/{self.progress_data.get('total_readings', 0)})")
    
    def increment_reading(self, document_name: str):
        """
        Increment reading progress by one (thread-safe)
        
        Args:
            document_name: Name of the document being read
        """
        with self._lock:
            current_completed = self.progress_data.get('completed_readings', 0)
            new_completed = current_completed + 1
            total = self.progress_data.get('total_readings', 0)
            self.progress_data.update({
                'completed_readings': new_completed,
                'current_activity': f'Completed reading {document_name}'
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Reading progress incremented: {document_name} ({new_completed}/{total})")
    
    def update_document_status(self, document_name: str, status: str):
        """
        Update the status of a specific document (thread-safe)
        
        Args:
            document_name: Name of the document
            status: Status of the document ("pending", "reading", "completed", "error")
        """
        with self._lock:
            current_time = time.time()
            
            if 'document_statuses' not in self.progress_data:
                self.progress_data['document_statuses'] = {}
            
            # Track document processing start time
            if status == "reading" and document_name not in self.document_processing_times:
                self.document_processing_times[document_name] = {'start_time': current_time, 'duration': 0}
            
            # Calculate processing duration when completed
            if status in ["completed", "error"] and document_name in self.document_processing_times:
                start_time = self.document_processing_times[document_name]['start_time']
                duration = current_time - start_time
                self.document_processing_times[document_name]['duration'] = duration
                self.document_processing_times[document_name]['end_time'] = current_time
            
            self.progress_data['document_statuses'][document_name] = status
            self.progress_data['document_processing_times'] = self.document_processing_times.copy()
            
            # Update activity message based on status
            if status == "reading":
                self.progress_data['current_activity'] = f'Reading {document_name}'
            elif status == "completed":
                duration = self.document_processing_times.get(document_name, {}).get('duration', 0)
                self.progress_data['current_activity'] = f'Completed {document_name} ({duration:.1f}s)'
            elif status == "error":
                self.progress_data['current_activity'] = f'Error reading {document_name}'
            
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Document status updated: {document_name} -> {status}")
    
    def update_aggregation(self):
        """Update when aggregation stage starts"""
        with self._lock:
            self.progress_data.update({
                'current_activity': 'Synthesizing final response'
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info("Aggregation stage started")
    
    def complete_session(self, success: bool = True, final_message: str = ""):
        """
        Complete the progress tracking session
        
        Args:
            success: Whether the session completed successfully
            final_message: Final status message
        """
        with self._lock:
            current_time = time.time()
            
            # Finalize current stage duration
            if self.current_stage != "idle" and self.stage_start_time:
                final_stage_duration = current_time - self.stage_start_time
                self.stage_durations[self.current_stage] = final_stage_duration
            
            self.current_stage = "completed" if success else "failed"
            status = final_message or ("Research completed successfully" if success else "Research failed")
            
            self.progress_data.update({
                'stage': self.current_stage,
                'status': status,
                'current_activity': status,
                'completed': True,
                'success': success,
                'stage_durations': self.stage_durations.copy(),
                'document_processing_times': self.document_processing_times.copy()
            })
            self._update_times()
        
        self._notify_callbacks()
        logger.info(f"Session completed: success={success}, message='{final_message}'")
    
    def _update_times(self):
        """Update elapsed time fields (must be called with lock held)"""
        if self.start_time:
            self.progress_data['elapsed_time'] = time.time() - self.start_time
        if self.stage_start_time:
            self.progress_data['stage_elapsed_time'] = time.time() - self.stage_start_time
    
    def _notify_callbacks(self):
        """Notify all registered callbacks (must be called with lock held)"""
        progress_copy = self.progress_data.copy()
        for callback in self.callbacks:
            try:
                callback(progress_copy)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
    
    def get_current_progress(self) -> Dict[str, Any]:
        """
        Get current progress data
        
        Returns:
            Dictionary with current progress information
        """
        with self._lock:
            self._update_times()
            return self.progress_data.copy()
    
    def get_stage_duration(self, stage: str) -> float:
        """
        Get the duration of a specific stage
        
        Args:
            stage: Name of the stage
            
        Returns:
            Duration in seconds, or 0 if stage not found
        """
        with self._lock:
            return self.stage_durations.get(stage, 0.0)
    
    def get_document_processing_time(self, document_name: str) -> float:
        """
        Get the processing time of a specific document
        
        Args:
            document_name: Name of the document
            
        Returns:
            Processing time in seconds, or 0 if document not found
        """
        with self._lock:
            doc_timing = self.document_processing_times.get(document_name, {})
            return doc_timing.get('duration', 0.0)

# Global progress tracker instance
_progress_tracker = None

def get_progress_tracker() -> ProgressTracker:
    """
    Get singleton instance of progress tracker
    
    Returns:
        ProgressTracker instance
    """
    global _progress_tracker
    if _progress_tracker is None:
        _progress_tracker = ProgressTracker()
    return _progress_tracker

# Convenience functions
def start_progress_session(query: str):
    """Start a progress tracking session"""
    get_progress_tracker().start_session(query)

def update_progress_stage(stage: str, status: str, activity: str = ""):
    """Update progress stage"""
    get_progress_tracker().update_stage(stage, status, activity)

def update_progress_retrieval(documents_found: int):
    """Update retrieval progress"""
    get_progress_tracker().update_retrieval(documents_found)

def update_progress_pruning(completed: int, total: int):
    """Update pruning progress"""
    get_progress_tracker().update_pruning(completed, total)

def update_progress_reading_start(documents: List[str], chunk_info: Dict[str, Dict] = None):
    """Update reading start"""
    get_progress_tracker().update_reading_start(documents, chunk_info)

def update_progress_reading(document_name: str, completed_count: int):
    """Update reading progress"""
    get_progress_tracker().update_reading_progress(document_name, completed_count)

def update_progress_aggregation():
    """Update aggregation stage"""
    get_progress_tracker().update_aggregation()

def complete_progress_session(success: bool = True, final_message: str = ""):
    """Complete progress session"""
    get_progress_tracker().complete_session(success, final_message)

if __name__ == "__main__":
    # Test the progress tracker
    import json
    
    def print_progress(data):
        print(f"Progress: {data['stage']} - {data['status']} - {data['current_activity']}")
    
    tracker = ProgressTracker()
    tracker.register_callback(print_progress)
    
    # Simulate a research session
    tracker.start_session("Test query about criminal cases")
    time.sleep(1)
    
    tracker.update_stage("retrieval", "Searching vector database")
    time.sleep(1)
    
    tracker.update_retrieval(25)
    time.sleep(1)
    
    tracker.update_stage("pruning", "Filtering relevant documents")
    for i in range(1, 6):
        tracker.update_pruning(i, 5)
        time.sleep(0.5)
    
    tracker.update_stage("reading", "Extracting information")
    docs = ["R. v. Smith", "R. v. Jones", "R. v. Brown"]
    tracker.update_reading_start(docs)
    
    for i, doc in enumerate(docs):
        tracker.update_reading_progress(doc, i + 1)
        time.sleep(0.5)
    
    # Test aggregation stage (removed duplicate call)
    tracker.update_stage("aggregation", "Finalizing response")
    time.sleep(1)
    
    tracker.complete_session(True, "Research completed successfully")
    
    final_progress = tracker.get_current_progress()
    print(f"\nFinal progress: {json.dumps(final_progress, indent=2)}")
