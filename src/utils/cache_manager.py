"""
Cache manager for vector database to avoid re-indexing unchanged documents
"""
import os
import json
import hashlib
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

class CacheManager:
    """Manages caching for document indexing to avoid re-processing unchanged documents"""
    
    def __init__(self, cache_file: str = "chroma_db/.cache_manifest.json"):
        """
        Initialize cache manager
        
        Args:
            cache_file: Path to cache manifest file
        """
        self.cache_file = cache_file
        
    def generate_manifest(self, documents_dir: str) -> Dict[str, any]:
        """
        Generate a manifest of all documents with their modification times
        
        Args:
            documents_dir: Directory containing documents
            
        Returns:
            Dictionary with file paths as keys and file info as values
        """
        manifest = {}
        
        if not os.path.exists(documents_dir):
            logger.warning(f"Documents directory not found: {documents_dir}")
            return manifest
        
        for root, dirs, files in os.walk(documents_dir):
            for file in files:
                if file.endswith('.txt'):
                    file_path = os.path.join(root, file)
                    try:
                        stat_info = os.stat(file_path)
                        manifest[file_path] = {
                            'size': stat_info.st_size,
                            'modified': stat_info.st_mtime,
                            'name': file
                        }
                    except Exception as e:
                        logger.warning(f"Could not get stats for {file_path}: {e}")
        
        return manifest
    
    def load_cached_manifest(self) -> Dict[str, any]:
        """
        Load cached manifest from file
        
        Returns:
            Cached manifest dictionary or empty dict if not found
        """
        if not os.path.exists(self.cache_file):
            return {}
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load cache manifest: {e}")
            return {}
    
    def save_manifest(self, manifest: Dict[str, any]):
        """
        Save manifest to cache file
        
        Args:
            manifest: Manifest dictionary to save
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
            
            logger.info(f"Saved cache manifest with {len(manifest)} files")
        except Exception as e:
            logger.error(f"Could not save cache manifest: {e}")
    
    def has_changes(self, documents_dir: str) -> Tuple[bool, str]:
        """
        Check if documents have changed since last indexing
        
        Args:
            documents_dir: Directory containing documents
            
        Returns:
            Tuple of (has_changes: bool, reason: str)
        """
        current_manifest = self.generate_manifest(documents_dir)
        cached_manifest = self.load_cached_manifest()
        
        if not cached_manifest:
            return True, "No cache found - first time indexing"
        
        # Check if number of files changed
        if len(current_manifest) != len(cached_manifest):
            return True, f"Number of files changed: {len(cached_manifest)} -> {len(current_manifest)}"
        
        # Check if any files were added, removed, or modified
        current_files = set(current_manifest.keys())
        cached_files = set(cached_manifest.keys())
        
        added_files = current_files - cached_files
        removed_files = cached_files - current_files
        
        if added_files:
            return True, f"Added files: {len(added_files)} new file(s)"
        
        if removed_files:
            return True, f"Removed files: {len(removed_files)} file(s) deleted"
        
        # Check if any existing files were modified
        modified_files = []
        for file_path in current_files:
            current_info = current_manifest[file_path]
            cached_info = cached_manifest.get(file_path, {})
            
            if (current_info.get('modified') != cached_info.get('modified') or 
                current_info.get('size') != cached_info.get('size')):
                modified_files.append(file_path)
        
        if modified_files:
            return True, f"Modified files: {len(modified_files)} file(s) changed"
        
        return False, "No changes detected"
    
    def update_cache(self, documents_dir: str):
        """
        Update cache with current document state
        
        Args:
            documents_dir: Directory containing documents
        """
        manifest = self.generate_manifest(documents_dir)
        self.save_manifest(manifest)


def create_cache_manager() -> CacheManager:
    """Factory function to create cache manager instance"""
    return CacheManager()
