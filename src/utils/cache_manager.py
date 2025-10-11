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
        
    def _calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate SHA256 hash of file content for reliable change detection
        
        Args:
            file_path: Path to file
            
        Returns:
            SHA256 hash as hex string
        """
        hash_obj = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                # Read in chunks to handle large files efficiently
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception as e:
            logger.warning(f"Could not hash file {file_path}: {e}")
            return ""
    
    def generate_manifest(self, documents_dir: str, use_hash: bool = True) -> Dict[str, any]:
        """
        Generate a manifest of all documents with their content hashes
        
        Args:
            documents_dir: Directory containing documents
            use_hash: If True, use content hash; if False, use timestamps (faster but less reliable)
            
        Returns:
            Dictionary with file paths as keys and file info as values
        """
        manifest = {}
        
        if not os.path.exists(documents_dir):
            logger.warning(f"Documents directory not found: {documents_dir}")
            return manifest
        
        file_count = 0
        for root, dirs, files in os.walk(documents_dir):
            for file in files:
                if file.endswith('.txt'):
                    file_path = os.path.join(root, file)
                    try:
                        stat_info = os.stat(file_path)
                        file_info = {
                            'size': stat_info.st_size,
                            'modified': stat_info.st_mtime,
                            'name': file
                        }
                        
                        # Add content hash for reliable change detection
                        if use_hash:
                            file_info['hash'] = self._calculate_file_hash(file_path)
                        
                        manifest[file_path] = file_info
                        file_count += 1
                        
                        # Log progress for large directories
                        if file_count % 100 == 0:
                            logger.info(f"Generated manifest for {file_count} files...")
                            
                    except Exception as e:
                        logger.warning(f"Could not get stats for {file_path}: {e}")
        
        logger.info(f"Generated manifest for {file_count} files")
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
    
    def has_changes(self, documents_dir: str, use_hash: bool = True, quick_check: bool = False) -> Tuple[bool, str]:
        """
        Check if documents have changed since last indexing
        
        Args:
            documents_dir: Directory containing documents
            use_hash: If True, use content hash for comparison (slower but accurate)
                     If False, use size and timestamp (faster but may miss some changes)
            quick_check: If True, only check file count and sizes (very fast)
            
        Returns:
            Tuple of (has_changes: bool, reason: str)
        """
        cached_manifest = self.load_cached_manifest()
        
        if not cached_manifest:
            return True, "No cache found - first time indexing"
        
        # Quick check: just count files
        if quick_check:
            current_manifest = self.generate_manifest(documents_dir, use_hash=False)
            if len(current_manifest) != len(cached_manifest):
                return True, f"Number of files changed: {len(cached_manifest)} -> {len(current_manifest)}"
            return False, "Quick check passed - assuming no changes"
        
        # Full check with optional hashing
        logger.info("Checking for document changes...")
        current_manifest = self.generate_manifest(documents_dir, use_hash=use_hash)
        
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
            
            # First check size (fast)
            if current_info.get('size') != cached_info.get('size'):
                modified_files.append(file_path)
                continue
            
            # If using hash, compare hashes (reliable)
            if use_hash:
                if current_info.get('hash') != cached_info.get('hash'):
                    modified_files.append(file_path)
            else:
                # Fallback to timestamp comparison (less reliable)
                if current_info.get('modified') != cached_info.get('modified'):
                    modified_files.append(file_path)
        
        if modified_files:
            return True, f"Modified files: {len(modified_files)} file(s) changed"
        
        logger.info(f"✓ No changes detected in {len(current_files)} files")
        return False, "No changes detected"
    
    def update_cache(self, documents_dir: str, use_hash: bool = True):
        """
        Update cache with current document state
        
        Args:
            documents_dir: Directory containing documents
            use_hash: If True, include content hashes in manifest
        """
        logger.info("Updating cache manifest...")
        manifest = self.generate_manifest(documents_dir, use_hash=use_hash)
        self.save_manifest(manifest)
        logger.info(f"✓ Cache updated with {len(manifest)} files")


def create_cache_manager() -> CacheManager:
    """Factory function to create cache manager instance"""
    return CacheManager()
