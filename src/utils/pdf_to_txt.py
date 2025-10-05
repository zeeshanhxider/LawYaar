import os
import re
import csv
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import PyPDF2

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PDFToTextConverter:
    """
    Converts Supreme Court of Pakistan judgment PDFs to formatted text files
    with proper metadata headers and cleaned judgment content.
    """
    
    def __init__(self, 
                 pdf_dir: str = "scraper/raw_pdfs",
                 metadata_csv: str = "scraper/metadata.csv",
                 output_dir: str = "src/assets/data"):
        """
        Initialize the PDF to text converter
        
        Args:
            pdf_dir: Directory containing PDF files
            metadata_csv: Path to CSV file containing case metadata
            output_dir: Directory to save processed text files
        """
        self.pdf_dir = Path(pdf_dir)
        self.metadata_csv = Path(metadata_csv)
        self.output_dir = Path(output_dir)
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load metadata from CSV
        self.metadata_dict = self._load_metadata()
        
        logger.info(f"Initialized PDFToTextConverter")
        logger.info(f"PDF Directory: {self.pdf_dir}")
        logger.info(f"Output Directory: {self.output_dir}")
        logger.info(f"Loaded metadata for {len(self.metadata_dict)} cases")
    
    def _load_metadata(self) -> Dict[str, Dict[str, str]]:
        """
        Load metadata from CSV file into a dictionary keyed by filename
        
        Returns:
            Dictionary mapping filename to metadata dict
        """
        metadata_dict = {}
        
        if not self.metadata_csv.exists():
            logger.warning(f"Metadata CSV not found: {self.metadata_csv}")
            return metadata_dict
        
        try:
            with open(self.metadata_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    filename = row.get('Filename', '')
                    if filename and filename != 'N/A':
                        metadata_dict[filename] = row
            
            logger.info(f"Loaded {len(metadata_dict)} metadata entries from CSV")
        except Exception as e:
            logger.error(f"Error loading metadata CSV: {e}")
        
        return metadata_dict
    
    def _extract_text_from_pdf(self, pdf_path: Path) -> Optional[str]:
        """
        Extract raw text from PDF file
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text or None if extraction fails
        """
        try:
            with open(pdf_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                
                text_parts = []
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                    except Exception as e:
                        logger.warning(f"Error extracting page {page_num} from {pdf_path.name}: {e}")
                
                full_text = '\n'.join(text_parts)
                
                if not full_text.strip():
                    logger.warning(f"No text extracted from {pdf_path.name}")
                    return None
                
                return full_text
        
        except Exception as e:
            logger.error(f"Error reading PDF {pdf_path.name}: {e}")
            return None
    
    def _find_judgment_start(self, text: str) -> int:
        """
        Find the starting position of the judgment text
        Looks for "JUDGMENT" or "ORDER" (case-insensitive)
        
        Args:
            text: Full PDF text
            
        Returns:
            Index where judgment starts, or 0 if not found
        """
        # Look for common judgment start markers
        patterns = [
            r'\bJUDGMENT\b',
            r'\bJUDGEMENT\b',
            r'\bORDER\b',
            r'\bJ\s*U\s*D\s*G\s*M\s*E\s*N\s*T\b',  # Spaced out
        ]
        
        earliest_match = len(text)
        found = False
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                found = True
                earliest_match = min(earliest_match, match.start())
        
        if found:
            logger.debug(f"Found judgment start at position {earliest_match}")
            return earliest_match
        else:
            logger.warning("Could not find judgment start marker, using full text")
            return 0
    
    def _clean_judgment_text(self, text: str) -> str:
        """
        Clean and format the judgment text with consistent sequential numbering
        
        Args:
            text: Raw judgment text
            
        Returns:
            Cleaned and formatted text with [1], [2], [3] numbering
        """
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove page numbers (common patterns)
        text = re.sub(r'\bPage\s+\d+\s+of\s+\d+\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\b\d+\s*/\s*\d+\b', '', text)
        
        # Remove common footer/header patterns
        text = re.sub(r'\bSupreme Court of Pakistan\b.*?\n', '', text, flags=re.IGNORECASE)
        
        # Remove trailing signatures, dates at the end
        text = re.sub(r'\n\s*(Dated|Date|Sd/-|Judge|Justice|Islamabad).*$', '', text, flags=re.IGNORECASE)
        
        # Strategy: Split text into meaningful paragraphs and number them sequentially
        # Remove any existing numbering patterns to avoid conflicts
        text = re.sub(r'^\s*\[?\d+\]?\.?\s+', '', text, flags=re.MULTILINE)
        
        # Split into sentences first
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        
        # Group sentences into paragraphs (logical chunks)
        paragraphs = []
        current_paragraph = []
        min_paragraph_length = 100  # Minimum characters for a paragraph
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            current_paragraph.append(sentence)
            current_text = ' '.join(current_paragraph)
            
            # Create a new paragraph if:
            # 1. Current text is substantial (>300 chars) and ends with period
            # 2. Or it's very long (>600 chars)
            if (len(current_text) > 300 and sentence.endswith('.')) or len(current_text) > 600:
                paragraphs.append(current_text)
                current_paragraph = []
        
        # Add remaining content
        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))
        
        # Filter out very short paragraphs and number sequentially
        formatted_parts = []
        paragraph_number = 1
        
        for para in paragraphs:
            para = para.strip()
            # Only include substantial paragraphs
            if len(para) >= min_paragraph_length:
                formatted_parts.append(f"[{paragraph_number}] {para}")
                paragraph_number += 1
        
        # If no paragraphs were created (text too short or unusual structure),
        # treat the whole text as one paragraph
        if not formatted_parts and text.strip():
            formatted_parts.append(f"[1] {text.strip()}")
        
        # Join with double newlines for readability
        final_text = '\n\n'.join(formatted_parts)
        
        # Final cleanup
        final_text = final_text.strip()
        
        return final_text
    
    def _create_metadata_header(self, metadata: Dict[str, str]) -> str:
        """
        Create formatted metadata header for text file
        
        Args:
            metadata: Dictionary containing case metadata
            
        Returns:
            Formatted metadata header string
        """
        header_lines = [
            f"Case No: {metadata.get('Case_No', 'N/A')}",
            f"Case Title: {metadata.get('Case_Title', 'N/A')}",
            f"Subject: {metadata.get('Case_Subject', 'N/A')}",
            f"Judge: {metadata.get('Author_Judge', 'N/A')}",
            f"Judgment Date: {metadata.get('Judgment_Date', 'N/A')}",
            f"Upload Date: {metadata.get('Upload_Date', 'N/A')}",
            f"Citations: {metadata.get('Citations', 'N/A')}",
            f"SC Citations: {metadata.get('SC_Citations', 'N/A')}",
            f"PDF URL: {metadata.get('PDF_URL', 'N/A')}",
            ""
        ]
        
        return '\n'.join(header_lines)
    
    def process_pdf(self, pdf_path: Path) -> bool:
        """
        Process a single PDF file: extract text, format, and save
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Processing: {pdf_path.name}")
        
        # Get metadata for this file
        filename = pdf_path.name
        metadata = self.metadata_dict.get(filename, {})
        
        if not metadata:
            logger.warning(f"No metadata found for {filename}, using defaults")
            metadata = {
                'Case_No': 'Unknown',
                'Case_Title': 'Unknown',
                'Case_Subject': 'Unknown',
                'Author_Judge': 'Unknown',
                'Judgment_Date': 'Unknown',
                'Upload_Date': 'Unknown',
                'Citations': 'N/A',
                'SC_Citations': 'N/A',
                'PDF_URL': 'N/A'
            }
        
        # Extract text from PDF
        raw_text = self._extract_text_from_pdf(pdf_path)
        if not raw_text:
            logger.error(f"Failed to extract text from {filename}")
            return False
        
        # Find judgment start
        judgment_start = self._find_judgment_start(raw_text)
        judgment_text = raw_text[judgment_start:]
        
        # Clean and format judgment text
        cleaned_text = self._clean_judgment_text(judgment_text)
        
        if not cleaned_text:
            logger.warning(f"No judgment text after cleaning for {filename}")
            return False
        
        # Create metadata header
        header = self._create_metadata_header(metadata)
        
        # Combine header and judgment
        final_text = header + '\n' + cleaned_text
        
        # Save to output file
        output_filename = pdf_path.stem + '.txt'
        output_path = self.output_dir / output_filename
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(final_text)
            
            logger.info(f"Successfully saved: {output_filename}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving text file {output_filename}: {e}")
            return False
    
    def process_all_pdfs(self) -> Tuple[int, int]:
        """
        Process all PDF files in the PDF directory
        
        Returns:
            Tuple of (successful_count, failed_count)
        """
        if not self.pdf_dir.exists():
            logger.error(f"PDF directory does not exist: {self.pdf_dir}")
            return 0, 0
        
        pdf_files = list(self.pdf_dir.glob("*.pdf"))
        
        if not pdf_files:
            logger.warning(f"No PDF files found in {self.pdf_dir}")
            return 0, 0
        
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        successful = 0
        failed = 0
        
        for pdf_path in pdf_files:
            try:
                if self.process_pdf(pdf_path):
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Unexpected error processing {pdf_path.name}: {e}")
                failed += 1
        
        logger.info(f"Processing complete: {successful} successful, {failed} failed")
        return successful, failed


def main():
    """Main entry point for the script"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert Supreme Court of Pakistan judgment PDFs to formatted text files'
    )
    parser.add_argument(
        '--pdf-dir',
        default='scraper/raw_pdfs',
        help='Directory containing PDF files (default: scraper/raw_pdfs)'
    )
    parser.add_argument(
        '--metadata-csv',
        default='scraper/metadata.csv',
        help='Path to metadata CSV file (default: scraper/metadata.csv)'
    )
    parser.add_argument(
        '--output-dir',
        default='src/assets/data',
        help='Directory to save text files (default: src/assets/data)'
    )
    parser.add_argument(
        '--single-file',
        help='Process only a single PDF file (provide filename)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create converter
    converter = PDFToTextConverter(
        pdf_dir=args.pdf_dir,
        metadata_csv=args.metadata_csv,
        output_dir=args.output_dir
    )
    
    # Process files
    if args.single_file:
        pdf_path = Path(args.pdf_dir) / args.single_file
        if pdf_path.exists():
            success = converter.process_pdf(pdf_path)
            if success:
                print(f"✓ Successfully processed {args.single_file}")
            else:
                print(f"✗ Failed to process {args.single_file}")
        else:
            print(f"✗ File not found: {pdf_path}")
    else:
        successful, failed = converter.process_all_pdfs()
        print(f"\n{'='*60}")
        print(f"Processing Summary:")
        print(f"  Successful: {successful}")
        print(f"  Failed: {failed}")
        print(f"  Total: {successful + failed}")
        print(f"  Output directory: {converter.output_dir}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
