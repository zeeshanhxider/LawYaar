"""
Quick test script to verify cache functionality
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from utils.cache_manager import create_cache_manager
from utils.vector_db import create_vector_db
from config import get_system_config, get_vector_db_config

def test_cache():
    print("Testing Cache System")
    print("="*50)
    
    config = get_system_config()
    vdb_config = get_vector_db_config()
    cache_manager = create_cache_manager()
    vector_db = create_vector_db()
    
    # Test 1: Check if collection exists
    print("\n1. Checking if vector DB collection exists...")
    exists = vector_db.collection_exists(vdb_config.COLLECTION_NAME)
    print(f"   Collection exists: {exists}")
    
    if exists:
        stats = vector_db.get_collection_stats()
        print(f"   Documents in collection: {stats['total_documents']}")
    
    # Test 2: Check cache status
    print("\n2. Checking cache status...")
    has_changes, reason = cache_manager.has_changes(config.DOCUMENTS_DIR)
    
    if has_changes:
        print(f"   ⟳ Re-indexing would be required")
        print(f"   Reason: {reason}")
    else:
        print(f"   ✓ Cache is valid - can use existing DB")
        print(f"   Reason: {reason}")
    
    # Test 3: Show current manifest
    print("\n3. Current document manifest...")
    manifest = cache_manager.generate_manifest(config.DOCUMENTS_DIR)
    print(f"   Total files: {len(manifest)}")
    if manifest:
        print(f"   Sample files:")
        for i, (path, info) in enumerate(list(manifest.items())[:3]):
            print(f"   - {info['name']} (size: {info['size']} bytes)")
    
    # Test 4: Cache file status
    print("\n4. Cache file status...")
    cache_file = cache_manager.cache_file
    if os.path.exists(cache_file):
        print(f"   ✓ Cache file exists: {cache_file}")
        cached_manifest = cache_manager.load_cached_manifest()
        print(f"   Cached files: {len(cached_manifest)}")
    else:
        print(f"   ✗ Cache file not found: {cache_file}")
        print(f"   (Will be created after first indexing)")
    
    print("\n" + "="*50)
    print("Test completed!")

if __name__ == "__main__":
    test_cache()
