# Message Processing Tracker
# Keeps track of processed message IDs to prevent duplicates

import time

class MessageTracker:
    """Track processed messages to prevent duplicate processing."""
    
    def __init__(self, expiry_seconds=3600):
        """
        Initialize the message tracker.
        
        Args:
            expiry_seconds (int): How long to keep message IDs (default 1 hour)
        """
        self.processed_messages = {}  # {message_id: timestamp}
        self.expiry_seconds = expiry_seconds
    
    def is_processed(self, message_id):
        """
        Check if a message has already been processed.
        
        Args:
            message_id (str): The WhatsApp message ID
            
        Returns:
            bool: True if already processed, False otherwise
        """
        # Clean up old entries
        self._cleanup_old_entries()
        
        return message_id in self.processed_messages
    
    def mark_processed(self, message_id):
        """
        Mark a message as processed.
        
        Args:
            message_id (str): The WhatsApp message ID
        """
        self.processed_messages[message_id] = time.time()
    
    def _cleanup_old_entries(self):
        """Remove expired message IDs from the tracker."""
        current_time = time.time()
        expired_ids = [
            msg_id for msg_id, timestamp in self.processed_messages.items()
            if current_time - timestamp > self.expiry_seconds
        ]
        for msg_id in expired_ids:
            del self.processed_messages[msg_id]

# Global tracker instance
_tracker = MessageTracker()

def get_message_tracker():
    """Get the global message tracker instance."""
    return _tracker
