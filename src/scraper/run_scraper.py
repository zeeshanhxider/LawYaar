"""
Script to run the Supreme Court scraper with command-line arguments.
"""

import argparse
import sys
import os

# Add parent directory to path to import scraper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper import SupremeCourtScraper


def main():
    """Main entry point for the scraper."""
    parser = argparse.ArgumentParser(
        description="Scrape judgments from Supreme Court of Pakistan website"
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default='raw_pdfs',
        help='Directory to save downloaded PDFs (default: raw_pdfs)'
    )
    
    parser.add_argument(
        '--metadata-file',
        type=str,
        default='metadata.csv',
        help='CSV file to save metadata (default: metadata.csv)'
    )
    
    parser.add_argument(
        '--max-records',
        type=int,
        default=None,
        help='Maximum number of records to process (default: all records)'
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: only process first 10 records'
    )
    
    parser.add_argument(
        '--auto',
        action='store_true',
        help='Automatic mode: try to click search button automatically (default is manual mode)'
    )
    
    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help='Maximum number of pages to scrape (default: all pages)'
    )
    
    args = parser.parse_args()
    
    # Use test mode if specified
    max_records = 10 if args.test else args.max_records
    
    print(f"\n{'='*60}")
    print("Supreme Court of Pakistan Judgment Scraper")
    print(f"{'='*60}\n")
    
    if args.test:
        print("Running in TEST MODE - will only process 10 records\n")
    
    try:
        # Initialize scraper
        scraper = SupremeCourtScraper(
            output_dir=args.output_dir,
            metadata_file=args.metadata_file
        )
        
        # Run scraper (manual mode by default, automatic if --auto flag is used)
        scraper.scrape(
            max_records=max_records, 
            manual_mode=not args.auto,
            max_pages=args.max_pages
        )
        
    except KeyboardInterrupt:
        print("\n\nScraping interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError running scraper: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
