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
        Extract metadata from the beginning of a Supreme Court of Pakistan legal case file
        
        Expected format:
        ======================================================================
        SUPREME COURT OF PAKISTAN JUDGMENT
        ======================================================================
        
        Case No: C.P.L.A.379-L/2021
        Case Title: Ch. Bashir Ahmad v. Qamar Aftab, etc
        Subject: Rent/Rent/Ejectment
        Judge: Mr. Justice Muhammad Shafi Siddiqui
        Judgment Date: 18-09-2025
        Upload Date: 04-10-2025
        Citations: N/A
        SC Citations: N/A
        PDF URL: https://www.supremecourt.gov.pk/downloads_judgements/...
        
        ======================================================================
        
        [Main judgment text starts here...]
        
        Args:
            text: Full text of the legal case file
            
        Returns:
            Tuple of (metadata_dict, content_without_metadata)
        """
        lines = text.split('\n')
        metadata = {}
        content_start_idx = 0
        in_metadata_section = False
        separator_count = 0
        
        # Look for metadata patterns at the beginning
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Detect separator lines (===)
            if line_stripped.startswith('=') and len(line_stripped) > 30:
                separator_count += 1
                # After second separator, metadata section ends
                if separator_count >= 2:
                    in_metadata_section = False
                    content_start_idx = i + 1
                    break
                else:
                    in_metadata_section = True
                continue
            
            # Skip header lines
            if 'SUPREME COURT' in line_stripped.upper() or 'PAKISTAN' in line_stripped.upper():
                continue
            
            # Skip empty lines
            if not line_stripped:
                continue
            
            # Extract key-value pairs in metadata section
            if in_metadata_section and ':' in line_stripped:
                parts = line_stripped.split(':', 1)
                if len(parts) == 2:
                    key, value = parts
                    key = key.strip()
                    value = value.strip()
                    
                    # Map to standardized field names (matching CSV format)
                    key_lower = key.lower()
                    
                    if 'case no' in key_lower or 'case_no' in key_lower:
                        metadata['case_no'] = value
                    elif 'case title' in key_lower or 'case_title' in key_lower:
                        metadata['case_title'] = value
                    elif 'subject' in key_lower:
                        metadata['case_subject'] = value
                    elif 'judge' in key_lower:
                        metadata['author_judge'] = value
                    elif 'judgment date' in key_lower or 'judgment_date' in key_lower:
                        metadata['judgment_date'] = value
                    elif 'upload date' in key_lower or 'upload_date' in key_lower:
                        metadata['upload_date'] = value
                    elif 'sc citation' in key_lower or 'sc_citation' in key_lower:
                        metadata['sc_citations'] = value if value.lower() != 'n/a' else ''
                    elif 'citation' in key_lower:
                        metadata['citations'] = value if value.lower() != 'n/a' else ''
                    elif 'pdf url' in key_lower or 'pdf_url' in key_lower:
                        metadata['pdf_url'] = value
        
        # Extract the main content (everything after second separator)
        if content_start_idx > 0:
            content = '\n'.join(lines[content_start_idx:]).strip()
        else:
            # Fallback: if no separators found, look for first substantial paragraph
            content = text
        
        # Add derived metadata
        # Extract year from judgment_date or upload_date
        for field in ['judgment_date', 'upload_date']:
            if field in metadata:
                year_match = re.search(r'20\d{2}', metadata[field])
                if year_match:
                    metadata['year'] = year_match.group()
                    break
        
        # Set court name (always Supreme Court of Pakistan for this system)
        metadata['court'] = 'Supreme Court of Pakistan'
        
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
        Validate if a file appears to be a properly formatted Supreme Court of Pakistan legal case
        
        Args:
            file_info: Processed file information
            
        Returns:
            True if file appears to be a valid legal case format
        """
        metadata = file_info.get('metadata', {})
        content = file_info.get('content', '')
        
        # Check for essential metadata fields for Supreme Court of Pakistan
        required_fields = ['case_no', 'court']
        has_required_fields = all(field in metadata for field in required_fields)
        
        # At least one date field should be present
        has_date = 'judgment_date' in metadata or 'upload_date' in metadata
        
        # Check for substantial content
        has_content = len(content.strip()) > 100
        
        # Check for Pakistani legal case indicators in content
        legal_indicators = [
            'court', 'judgment', 'justice', 'appellant', 'respondent', 
            'section', 'supreme court', 'pakistan', 'petitioner', 
            'appeal', 'constitution', 'honourable'
        ]
        has_legal_content = any(indicator.lower() in content.lower() for indicator in legal_indicators)
        
        is_valid = has_required_fields and has_date and has_content and has_legal_content
        
        if not is_valid:
            logger.warning(f"File validation failed: {file_info.get('file_name', 'unknown')}")
            logger.warning(f"  Has required fields: {has_required_fields}")
            logger.warning(f"  Has date: {has_date}")
            logger.warning(f"  Has content: {has_content}")
            logger.warning(f"  Has legal content: {has_legal_content}")
        
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
