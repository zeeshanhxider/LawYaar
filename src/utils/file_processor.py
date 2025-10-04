import os
import re
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class LegalFileProcessor:
    def __init__(self):
        """Initialize the legal file processor"""
        pass
    
    def extract_metadata_from_text(self, text: str) -> Tuple[Dict[str, str], str]:
        """
        Extract metadata from the beginning of a legal case file
        
        Args:
            text: Full text of the legal case file
            
        Returns:
            Tuple of (metadata_dict, content_without_metadata)
        """
        lines = text.split('\n')
        metadata = {}
        content_start_idx = 0
        
        # Look for metadata patterns at the beginning
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Stop if we hit an empty line followed by substantial content
            if not line and i > 5:  # Allow some empty lines in metadata section
                # Check if next non-empty line looks like content
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip() and not ':' in lines[j][:50]:
                        content_start_idx = j
                        break
                if content_start_idx > 0:
                    break
            
            # Extract key-value pairs
            if ':' in line and len(line.split(':', 1)) == 2:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                # Clean up common metadata fields
                if key.lower() in ['link', 'date', 'file number', 'citation', 'court', 'region', 'client', 'judge']:
                    # Strip angle brackets from link field
                    if key.lower() == 'link' and value.startswith('<') and value.endswith('>'):
                        value = value[1:-1]
                    metadata[key.lower().replace(' ', '_')] = value
            
            # Stop metadata extraction if we see patterns indicating content start
            elif line.startswith('WARNING') or line.startswith('ONTARIO COURT') or 'CITATION:' in line:
                content_start_idx = i
                break
        
        # Extract the main content (everything after metadata)
        if content_start_idx > 0:
            content = '\n'.join(lines[content_start_idx:])
        else:
            # If no clear metadata section found, use the whole text
            content = text
        
        # Add derived metadata
        if 'citation' in metadata:
            # Extract case name from citation (e.g., "R. v. Smith, 2025 ONCJ 123")
            citation = metadata['citation']
            case_name_match = re.match(r'^([^,]+)', citation)
            if case_name_match:
                metadata['case_name'] = case_name_match.group(1).strip()
        
        # Extract year from date or citation
        for field in ['date', 'citation']:
            if field in metadata:
                year_match = re.search(r'20\d{2}', metadata[field])
                if year_match:
                    metadata['year'] = year_match.group()
                    break
        
        logger.info(f"Extracted metadata with {len(metadata)} fields")
        return metadata, content
    
    def process_file(self, file_path: str) -> Dict[str, any]:
        """
        Process a single legal case file
        
        Args:
            file_path: Path to the legal case file
            
        Returns:
            Dictionary with file information, metadata, and content
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                full_text = f.read()
            
            metadata, content = self.extract_metadata_from_text(full_text)
            
            # Add file-level metadata
            file_info = {
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'file_size': len(full_text),
                'content_length': len(content),
                'metadata': metadata,
                'content': content,
                'full_text': full_text
            }
            
            logger.info(f"Processed file: {file_path}")
            return file_info
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}")
            return {
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'error': str(e),
                'metadata': {},
                'content': '',
                'full_text': ''
            }
    
    def process_directory(self, directory_path: str, file_extension: str = ".txt") -> List[Dict[str, any]]:
        """
        Process all files in a directory
        
        Args:
            directory_path: Path to directory containing legal case files
            file_extension: File extension to filter by
            
        Returns:
            List of processed file dictionaries
        """
        processed_files = []
        
        if not os.path.exists(directory_path):
            logger.error(f"Directory does not exist: {directory_path}")
            return processed_files
        
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                if file.endswith(file_extension):
                    file_path = os.path.join(root, file)
                    processed_file = self.process_file(file_path)
                    processed_files.append(processed_file)
        
        logger.info(f"Processed {len(processed_files)} files from directory: {directory_path}")
        return processed_files
    
    def validate_legal_case_format(self, file_info: Dict[str, any]) -> bool:
        """
        Validate if a file appears to be a properly formatted legal case
        
        Args:
            file_info: Processed file information
            
        Returns:
            True if file appears to be a valid legal case format
        """
        metadata = file_info.get('metadata', {})
        content = file_info.get('content', '')
        
        # Check for essential metadata fields
        required_fields = ['citation', 'court', 'date']
        has_required_fields = all(field in metadata for field in required_fields)
        
        # Check for substantial content
        has_content = len(content.strip()) > 100
        
        # Check for legal case indicators in content
        legal_indicators = ['court', 'judgment', 'justice', 'appellant', 'respondent', 'section']
        has_legal_content = any(indicator.lower() in content.lower() for indicator in legal_indicators)
        
        is_valid = has_required_fields and has_content and has_legal_content
        
        if not is_valid:
            logger.warning(f"File validation failed: {file_info.get('file_name', 'unknown')}")
        
        return is_valid

def create_file_processor() -> LegalFileProcessor:
    """
    Factory function to create file processor
    """
    return LegalFileProcessor()

if __name__ == "__main__":
    # Test the file processor
    processor = LegalFileProcessor()
    
    # Test with a sample file (adjust path as needed)
    sample_file = "assets/data/case.txt"
    
    if os.path.exists(sample_file):
        file_info = processor.process_file(sample_file)
        
        print(f"File: {file_info['file_name']}")
        print(f"Metadata: {file_info['metadata']}")
        print(f"Content length: {file_info['content_length']}")
        print(f"Content preview: {file_info['content'][:200]}...")
        print(f"Valid legal case: {processor.validate_legal_case_format(file_info)}")
    else:
        print(f"Sample file not found: {sample_file}")
        
        # Test directory processing
        directory = "assets/data"
        if os.path.exists(directory):
            files = processor.process_directory(directory)
            print(f"\nProcessed {len(files)} files from directory")
            for file_info in files[:3]:  # Show first 3
                print(f"- {file_info['file_name']}: {len(file_info['metadata'])} metadata fields")
