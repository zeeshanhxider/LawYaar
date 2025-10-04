import re
import os
import sys
from pathlib import Path


def extract_metadata(text):
    """
    Extract metadata from legal document text.
    
    Args:
        text (str): The full text of the legal document
        
    Returns:
        dict: Dictionary containing extracted metadata
    """
    metadata = {}
    
    # Extract Citation (assumes format like "R. v. Chow, 2025 ONCJ 445")
    citation_pattern = r'CITATION:\s*(.+?)(?:\n|$)'
    citation_match = re.search(citation_pattern, text)
    metadata['Citation'] = citation_match.group(1).strip() if citation_match else 'Not found'
    
    # Extract Date - handle multiple formats
    date_found = False
    
    # Pattern 1: Standard format "DATE: 2025 08 28"
    date_pattern1 = r'DATE:\s*(\d{4}\s+\d{2}\s+\d{2})'
    date_match1 = re.search(date_pattern1, text)
    if date_match1:
        metadata['Date'] = date_match1.group(1).strip()
        date_found = True
    
    if not date_found:
        # Pattern 2: Month name format "DATE: August 27, 2025"
        date_pattern2 = r'DATE:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})'
        date_match2 = re.search(date_pattern2, text)
        if date_match2:
            metadata['Date'] = date_match2.group(1).strip()
            date_found = True
    
    if not date_found:
        # Pattern 3: HEARD or RULING format "HEARD: August 11, 2025" or "RULING: August 29, 2025"
        date_pattern3 = r'(?:HEARD|RULING):\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})'
        date_match3 = re.search(date_pattern3, text)
        if date_match3:
            metadata['Date'] = date_match3.group(1).strip()
            date_found = True
    
    if not date_found:
        # Pattern 4: Fallback - extract from first line "retrieved on 2025-09-14"
        retrieved_pattern = r'retrieved on (\d{4}-\d{2}-\d{2})'
        retrieved_match = re.search(retrieved_pattern, text)
        if retrieved_match:
            retrieved_date = retrieved_match.group(1)
            # Convert format from 2025-09-14 to 2025 09 14
            metadata['Date'] = retrieved_date.replace('-', ' ')
            date_found = True
    
    if not date_found:
        metadata['Date'] = 'Not found'
    
    # Extract Court File Number (assumes format like "Toronto / 24-48103094")
    file_num_pattern = r'COURT FILE No\.:\s*(.+?)(?:\n|$)'
    file_num_match = re.search(file_num_pattern, text)
    if file_num_match:
        full_file_info = file_num_match.group(1).strip()
        # Extract just the file number part (after the slash)
        file_num_parts = full_file_info.split('/')
        if len(file_num_parts) > 1:
            metadata['File number'] = file_num_parts[-1].strip()
            metadata['Region'] = file_num_parts[0].strip()
        else:
            metadata['File number'] = full_file_info
            metadata['Region'] = 'Not found'
    else:
        metadata['File number'] = 'Not found'
        metadata['Region'] = 'Not found'
    
    # Extract Court (look for court name in header)
    court_pattern = r'(ONTARIO COURT OF JUSTICE|SUPERIOR COURT OF JUSTICE|COURT OF APPEAL|SUPREME COURT)'
    court_match = re.search(court_pattern, text, re.IGNORECASE)
    if court_match:
        metadata['Court'] = court_match.group(1).title()
    else:
        metadata['Court'] = 'Not found'
    
    # Extract Client name using improved pattern:
    # Find "HIS MAJESTY THE KING" followed by "— AND —" (with possible newlines and extra text)
    # Then capture the next non-empty line as the client name, handling multiple formats
    
    # Pattern 1: Standard format - look for name after first "— AND —"
    between_pattern = r'HIS MAJESTY THE KING(?:\s*\([^)]+\))?\s*(?:\n\s*Respondent\s*)?\s*\n+\s*—\s*AND\s*—\s*\n+\s*([^\n]+?)(?:\s*\([^)]+\))?\s*(?:\n|$)'
    between_match = re.search(between_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if between_match:
        client_name = between_match.group(1).strip()
        # Clean up the name (remove extra whitespace, parenthetical info)
        client_name = re.sub(r'\s*\([^)]+\)\s*', '', client_name)  # Remove parenthetical
        client_name = ' '.join(client_name.split())  # Remove extra whitespace
        metadata['Client'] = client_name.title()
    else:
        # Pattern 2: Try a more flexible approach - look for any name after "— AND —"
        flexible_pattern = r'—\s*AND\s*—\s*\n+\s*([A-Z][A-Z\s\.,\']+?)(?:\s*\([^)]+\))?\s*(?:\n|$)'
        flexible_match = re.search(flexible_pattern, text, re.DOTALL)
        
        if flexible_match:
            client_name = flexible_match.group(1).strip()
            # Clean up the name
            client_name = re.sub(r'\s*\([^)]+\)\s*', '', client_name)  # Remove parenthetical
            client_name = ' '.join(client_name.split())  # Remove extra whitespace
            metadata['Client'] = client_name.title()
        else:
            # Fallback: try to extract from citation
            accused_pattern = r'R\.\s*v\.\s*([A-Za-z\s\.\,\']+?),'
            accused_match = re.search(accused_pattern, metadata.get('Citation', ''))
            if accused_match:
                client_name = accused_match.group(1).strip()
                metadata['Client'] = client_name
            else:
                metadata['Client'] = 'Not found'
    
    # Extract Judge (extract everything between "Before" and the next newline)
    judge_pattern = r'Before\s+(.+?)(?:\n|$)'
    judge_match = re.search(judge_pattern, text)
    metadata['Judge'] = judge_match.group(1).strip() if judge_match else 'Not found'
    
    # Extract CanLII link from header (format like "R. v. O'Kieffe, 2025 ONCJ 442 (CanLII), <https://canlii.ca/t/kf2z3>")
    canlii_pattern = r'<(https://canlii\.ca/t/[^>]+)>'
    canlii_match = re.search(canlii_pattern, text)
    metadata['Link'] = canlii_match.group(1) if canlii_match else 'Not found'
    
    return metadata


def format_metadata_output(metadata, original_text):
    """
    Format the metadata and original text for output.
    
    Args:
        metadata (dict): Extracted metadata
        original_text (str): Original document text
        
    Returns:
        str: Formatted output with metadata header and original text
    """
    output = ""
    output += f"Link: {metadata['Link']}\n"
    output += f"Date: {metadata['Date']}\n"
    output += f"File number: {metadata['File number']}\n"
    output += f"Citation: {metadata['Citation']}\n"
    output += f"Court: {metadata['Court']}\n"
    output += f"Region: {metadata['Region']}\n"
    output += f"Client: {metadata['Client']}\n"
    output += f"Judge: {metadata['Judge']}\n"
    output += "\n"
    output += original_text
    
    return output


def process_legal_documents(input_folder, output_folder):
    """
    Process all text files in input folder and save with metadata to output folder.
    
    Args:
        input_folder (str): Path to folder containing unprocessed text files
        output_folder (str): Path to folder where processed files will be saved
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    
    # Create output folder if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Check if input folder exists
    if not input_path.exists():
        print(f"Error: Input folder '{input_folder}' does not exist.")
        return
    
    # Get all text files in input folder
    text_files = list(input_path.glob("*.txt"))
    
    if not text_files:
        print(f"No .txt files found in '{input_folder}'")
        return
    
    print(f"Found {len(text_files)} text files to process...")
    
    processed_count = 0
    error_count = 0
    
    for file_path in text_files:
        try:
            print(f"Processing: {file_path.name}")
            
            # Read the file
            with open(file_path, 'r', encoding='utf-8') as f:
                text_content = f.read()
            
            # Extract metadata
            metadata = extract_metadata(text_content)
            
            # Determine output filename using citation
            citation = metadata.get('Citation', 'unknown')
            if citation == 'Not found' or citation == 'unknown':
                output_filename = f"{file_path.stem}_processed.txt"
                print(f"  Warning: Could not extract citation, using '{output_filename}'")
            else:
                # Clean citation for use as filename (remove invalid characters)
                clean_citation = re.sub(r'[<>:"/\\|?*]', '_', citation)
                output_filename = f"{clean_citation}.txt"
            
            # Format output with metadata
            formatted_output = format_metadata_output(metadata, text_content)
            
            # Save to output folder
            output_file_path = output_path / output_filename
            with open(output_file_path, 'w', encoding='utf-8') as f:
                f.write(formatted_output)
            
            print(f"  ✓ Saved as: {output_filename}")
            processed_count += 1
            
        except Exception as e:
            print(f"  ✗ Error processing {file_path.name}: {str(e)}")
            error_count += 1
    
    print(f"\nProcessing complete!")
    print(f"Successfully processed: {processed_count} files")
    print(f"Errors: {error_count} files")
    print(f"Output saved to: {output_folder}")


def main():
    """Main function to run the script."""
    print("Legal Document Metadata Extractor")
    print("=" * 40)
    
    # Get input and output folders from user or command line arguments
    if len(sys.argv) >= 3:
        input_folder = sys.argv[1]
        output_folder = sys.argv[2]
    else:
        input_folder = input("Enter input folder path: ").strip()
        output_folder = input("Enter output folder path: ").strip()
    
    if not input_folder or not output_folder:
        print("Error: Both input and output folder paths are required.")
        return
    
    process_legal_documents(input_folder, output_folder)


if __name__ == "__main__":
    main()