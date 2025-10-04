"""
Supreme Court of Pakistan Judgment Scraper

This module provides functionality to scrape judgments from the Supreme Court of Pakistan website.
It extracts PDF links, downloads them, and logs metadata for each case.
"""

import os
import time
import csv
import re
from typing import List, Dict, Optional
from datetime import datetime
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options


class SupremeCourtScraper:
    """Scraper for Supreme Court of Pakistan judgments."""
    
    def __init__(self, output_dir: str = "raw_pdfs", metadata_file: str = "metadata.csv"):
        """
        Initialize the scraper.
        
        Args:
            output_dir: Directory to save downloaded PDFs
            metadata_file: CSV file to log metadata
        """
        self.url = "https://www.supremecourt.gov.pk/judgement-search/#1573035933449-63bb4a39-ac81"
        self.output_dir = output_dir
        self.metadata_file = metadata_file
        self.driver = None
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize metadata CSV
        self._initialize_metadata_csv()
    
    def _initialize_metadata_csv(self):
        """Initialize the CSV file with headers if it doesn't exist."""
        if not os.path.exists(self.metadata_file):
            with open(self.metadata_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Sr_No', 'Case_No', 'Case_Title', 'Case_Subject', 'Author_Judge',
                    'Upload_Date', 'Judgment_Date', 'Citations', 'SC_Citations',
                    'PDF_URL', 'Filename', 'Download_Status', 'Timestamp'
                ])
    
    def _setup_driver(self):
        """Set up Chrome WebDriver with appropriate options."""
        chrome_options = Options()
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Uncomment the following line to run in headless mode
        # chrome_options.add_argument('--headless')
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.implicitly_wait(2)  # Reduced from 10 to 2 seconds
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename by removing invalid characters.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename
        """
        # Remove invalid characters for Windows filenames
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Limit length to avoid path length issues
        if len(filename) > 200:
            filename = filename[:200]
        return filename.strip()
    
    def navigate_to_page(self):
        """Navigate to the Supreme Court judgment search page."""
        print(f"Navigating to {self.url}")
        self.driver.get(self.url)
        time.sleep(3)  # Wait for page to load
    
    def click_search_button(self):
        """
        Click the Search Result button to load all records.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print("Looking for Search Result button...")
            # Wait for the search button to be clickable
            wait = WebDriverWait(self.driver, 20)
            
            # Try multiple possible selectors for the search button
            button_selectors = [
                "//button[contains(text(), 'Search Result')]",
                "//button[contains(@class, 'search')]",
                "//input[@type='submit' and contains(@value, 'Search')]",
                "//button[@type='submit']",
                "//a[contains(text(), 'Search')]"
            ]
            
            for selector in button_selectors:
                try:
                    button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    print(f"Found search button with selector: {selector}")
                    button.click()
                    print("Clicked Search Result button")
                    time.sleep(5)  # Wait for results to load
                    return True
                except (TimeoutException, NoSuchElementException):
                    continue
            
            print("Could not find Search Result button with any known selector")
            return False
            
        except Exception as e:
            print(f"Error clicking search button: {e}")
            return False
    
    def extract_records_from_current_page(self, current_record_index: int) -> List[Dict[str, str]]:
        """
        Extract record information from the current page.
        
        Args:
            current_record_index: Starting index for records (for continuous numbering across pages)
        
        Returns:
            List of dictionaries containing record information
        """
        records = []
        
        try:
            # Wait for results to load
            time.sleep(2)
            
            # Find tbody rows (the actual data rows)
            result_selectors = [
                "//tbody//tr",
                "//table[@id='results']//tr",
                "//div[@class='search-results']//div[@class='result-item']"
            ]
            
            elements = None
            for selector in result_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    if elements and len(elements) > 0:
                        break
                except NoSuchElementException:
                    continue
            
            if not elements:
                print("  ⚠ No records found on this page")
                return records
            
            # Extract information from each record
            for idx, element in enumerate(elements, start=1):
                try:
                    record = self._extract_record_info(element, current_record_index + idx - 1)
                    if record:
                        records.append(record)
                except Exception as e:
                    print(f"  Error extracting record {idx}: {e}")
                    continue
            
            # Count how many have PDF links
            with_pdfs = sum(1 for r in records if r.get('pdf_url') and r['pdf_url'] != 'NO_PDF_LINK_FOUND')
            print(f"  Extracted {len(records)} records ({with_pdfs} with PDFs, {len(records) - with_pdfs} without)")
            
        except Exception as e:
            print(f"  Error extracting records: {e}")
        
        return records
    
    def click_next_page(self) -> bool:
        """
        Click the next page button if it exists.
        
        Returns:
            True if next page button was clicked, False if no more pages
        """
        try:
            # DataTables pagination - look for "Next" button
            next_button_selectors = [
                "//a[contains(@class, 'paginate_button') and contains(@class, 'next') and not(contains(@class, 'disabled'))]",
                "//a[@id='DataTables_Table_0_next' and not(contains(@class, 'disabled'))]",
                "//li[contains(@class, 'next') and not(contains(@class, 'disabled'))]//a",
                "//a[contains(text(), 'Next')]",
                "//button[contains(text(), 'Next')]"
            ]
            
            for selector in next_button_selectors:
                try:
                    next_button = self.driver.find_element(By.XPATH, selector)
                    
                    # Check if button is enabled
                    classes = next_button.get_attribute('class')
                    if 'disabled' in classes:
                        return False
                    
                    # Scroll to button and click
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                    time.sleep(1)
                    
                    # Try regular click first
                    try:
                        next_button.click()
                    except:
                        # Use JavaScript click if regular click fails
                        self.driver.execute_script("arguments[0].click();", next_button)
                    
                    print("  ✓ Clicked Next button")
                    time.sleep(3)  # Wait for next page to load
                    return True
                    
                except NoSuchElementException:
                    continue
            
            print("  ℹ No more pages (Next button not found or disabled)")
            return False
            
        except Exception as e:
            print(f"  Error clicking next page: {e}")
            return False
    
    def get_current_page_info(self) -> dict:
        """
        Get information about current page (page number, total pages, etc.)
        
        Returns:
            Dictionary with page information
        """
        try:
            # Look for DataTables info text like "Showing 1 to 50 of 3,399 entries"
            info_selectors = [
                "//div[contains(@class, 'dataTables_info')]",
                "//div[@id='DataTables_Table_0_info']",
                "//div[contains(@class, 'table-info')]"
            ]
            
            for selector in info_selectors:
                try:
                    info_elem = self.driver.find_element(By.XPATH, selector)
                    info_text = info_elem.text
                    
                    # Parse text like "Showing 1 to 50 of 3,399 entries"
                    import re
                    match = re.search(r'Showing (\d+) to (\d+) of ([\d,]+) entries', info_text)
                    if match:
                        return {
                            'start': int(match.group(1)),
                            'end': int(match.group(2)),
                            'total': int(match.group(3).replace(',', '')),
                            'text': info_text
                        }
                except NoSuchElementException:
                    continue
            
            return {'start': 0, 'end': 0, 'total': 0, 'text': 'Unknown'}
            
        except Exception as e:
            print(f"  Error getting page info: {e}")
            return {'start': 0, 'end': 0, 'total': 0, 'text': 'Unknown'}
    
    def _extract_record_info(self, element, index: int) -> Optional[Dict[str, str]]:
        """
        Extract information from a single record element.
        
        Args:
            element: Selenium WebElement
            index: Record index
            
        Returns:
            Dictionary with record information or None
        """
        try:
            record = {'index': index}
            
            # Extract all table cells - Supreme Court table has 10 columns:
            # 0: Sr. No., 1: Case Subject, 2: Case No, 3: Case Title, 4: Author Judge,
            # 5: Upload Date, 6: Judgment Date, 7: Citation(s), 8: SCCitation(s), 9: Download
            try:
                cells = element.find_elements(By.TAG_NAME, "td")
                
                if len(cells) < 10:
                    # Skip header or incomplete rows
                    return None
                
                # Extract data from specific columns
                record['sr_no'] = cells[0].text.strip()
                record['case_subject'] = cells[1].text.strip() if cells[1].text.strip() else "N/A"
                record['case_no'] = cells[2].text.strip() if cells[2].text.strip() else "N/A"
                record['case_title'] = cells[3].text.strip() if cells[3].text.strip() else f"Case_{index}"
                record['author_judge'] = cells[4].text.strip() if cells[4].text.strip() else "N/A"
                record['upload_date'] = cells[5].text.strip() if cells[5].text.strip() else "N/A"
                record['judgment_date'] = cells[6].text.strip() if cells[6].text.strip() else "N/A"
                record['citations'] = cells[7].text.strip() if cells[7].text.strip() else "N/A"
                record['sc_citations'] = cells[8].text.strip() if cells[8].text.strip() else "N/A"
                
                # The download link is in the 10th column (index 9)
                pdf_link = None
                try:
                    download_cell = cells[9]
                    links = download_cell.find_elements(By.TAG_NAME, "a")
                    if links:
                        href = links[0].get_attribute('href')
                        if href and '.pdf' in href.lower():
                            pdf_link = href
                except Exception as e:
                    print(f"Error extracting PDF link from row {index}: {e}")
                
                record['pdf_url'] = pdf_link if pdf_link else "NO_PDF_LINK_FOUND"
                
                # Debug: print first record details
                if index == 1:
                    print(f"\nDEBUG - First record:")
                    print(f"  Case No: {record['case_no']}")
                    print(f"  Case Title: {record['case_title'][:60]}")
                    print(f"  Case Subject: {record['case_subject']}")
                    print(f"  Judgment Date: {record['judgment_date']}")
                    print(f"  PDF URL: {record['pdf_url']}")
                    print()
                    
            except Exception as e:
                print(f"Error extracting cells from row {index}: {e}")
                return None
            
            return record
            
        except Exception as e:
            print(f"Error extracting info from record {index}: {e}")
            return None
    
    def download_pdf(self, record: Dict[str, str]) -> bool:
        """
        Download a PDF file from the given URL.
        
        Args:
            record: Dictionary containing record information
            
        Returns:
            bool: True if download successful, False otherwise
        """
        try:
            pdf_url = record['pdf_url']
            index = record['index']
            case_no = record.get('case_no', f'Case_{index}')
            case_title = record.get('case_title', '')
            
            # Create filename using case number (more unique than title)
            sanitized_case_no = self._sanitize_filename(case_no)
            filename = f"{sanitized_case_no}.pdf"
            filepath = os.path.join(self.output_dir, filename)
            
            # Skip if file already exists
            if os.path.exists(filepath):
                print(f"File already exists: {filename}")
                record['filename'] = filename
                record['download_status'] = 'Already exists'
                return True
            
            # Download the PDF
            print(f"Downloading {index}: {case_no[:50]}...")
            response = requests.get(pdf_url, timeout=30, stream=True)
            response.raise_for_status()
            
            # Save the PDF
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            record['filename'] = filename
            record['download_status'] = 'Success'
            print(f"✓ Downloaded: {filename}")
            return True
            
        except Exception as e:
            print(f"✗ Error downloading PDF {case_no}: {e}")
            record['filename'] = "N/A"
            record['download_status'] = f'Failed: {str(e)}'
            return False
    
    def log_metadata(self, record: Dict[str, str]):
        """
        Log record metadata to CSV file.
        
        Args:
            record: Dictionary containing record information
        """
        try:
            with open(self.metadata_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    record.get('sr_no', 'N/A'),
                    record.get('case_no', 'N/A'),
                    record.get('case_title', 'N/A'),
                    record.get('case_subject', 'N/A'),
                    record.get('author_judge', 'N/A'),
                    record.get('upload_date', 'N/A'),
                    record.get('judgment_date', 'N/A'),
                    record.get('citations', 'N/A'),
                    record.get('sc_citations', 'N/A'),
                    record.get('pdf_url', 'N/A'),
                    record.get('filename', 'N/A'),
                    record.get('download_status', 'N/A'),
                    datetime.now().isoformat()
                ])
        except Exception as e:
            print(f"Error logging metadata: {e}")
    
    def scrape(self, max_records: Optional[int] = None, manual_mode: bool = True, max_pages: Optional[int] = None):
        """
        Main scraping method that orchestrates the entire process.
        
        Args:
            max_records: Maximum number of records to process (None for all)
            manual_mode: If True, wait for user to manually click search button
            max_pages: Maximum number of pages to scrape (None for all pages)
        """
        try:
            # Setup driver
            print("Setting up Chrome WebDriver...")
            self._setup_driver()
            
            # Navigate to page
            self.navigate_to_page()
            
            if manual_mode:
                # Manual click mode
                print("\n" + "="*60)
                print("MANUAL MODE:")
                print("  1. The browser window is now open")
                print("  2. Please click the 'Search Result' button")
                print("  3. Wait for all results to load completely")
                print("  4. Press ENTER in this terminal when ready...")
                print("="*60)
                input()
                print("✓ Continuing with scraping...\n")
                time.sleep(2)
            else:
                # Automatic click mode
                if not self.click_search_button():
                    print("Failed to click search button. Attempting to extract records anyway...")
                time.sleep(10)  # Wait for results to load
            
            # Get initial page info
            page_info = self.get_current_page_info()
            if page_info['total'] > 0:
                total_pages = (page_info['total'] + 49) // 50  # Assuming 50 records per page
                print(f"\nTotal entries: {page_info['total']}")
                print(f"Estimated pages: {total_pages}")
                if max_pages:
                    print(f"Will scrape: {min(max_pages, total_pages)} pages\n")
                else:
                    print(f"Will scrape: all {total_pages} pages\n")
            
            # Extract records from all pages
            all_records = []
            current_page = 1
            current_record_index = 1
            
            while True:
                # Get page info
                page_info = self.get_current_page_info()
                print(f"\n{'='*60}")
                print(f"PAGE {current_page} - {page_info['text']}")
                print(f"{'='*60}")
                
                # Extract records from current page
                records = self.extract_records_from_current_page(current_record_index)
                
                if not records:
                    print("  No records found on this page. Stopping.")
                    break
                
                all_records.extend(records)
                current_record_index += len(records)
                
                # Check if we've reached max records
                if max_records and len(all_records) >= max_records:
                    print(f"\nReached maximum records limit ({max_records})")
                    all_records = all_records[:max_records]
                    break
                
                # Check if we've reached max pages BEFORE clicking next
                if max_pages and current_page >= max_pages:
                    print(f"\nReached maximum pages limit ({max_pages})")
                    break
                
                # Try to go to next page
                print("\n  Checking for next page...")
                if not self.click_next_page():
                    print("  No more pages available")
                    break
                
                current_page += 1
            
            print(f"\n{'='*60}")
            print(f"EXTRACTION COMPLETE")
            print(f"{'='*60}")
            print(f"Total pages scraped: {current_page}")
            print(f"Total records extracted: {len(all_records)}")
            
            records = all_records
            
            if not records:
                print("\nNo records found. Saving page source for debugging...")
                with open("page_source_debug.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                print("Page source saved to page_source_debug.html")
                print("\nPlease check the HTML structure and update the selectors in the code.")
                return
            
            # Download PDFs and log metadata
            successful = 0
            failed = 0
            no_pdf = 0
            
            print(f"\nStarting downloads...\n")
            
            for record in records:
                # Skip if no PDF URL
                if record.get('pdf_url') == 'NO_PDF_LINK_FOUND' or not record.get('pdf_url'):
                    print(f"Record {record['index']}: No PDF link - skipping download")
                    record['filename'] = 'N/A'
                    record['download_status'] = 'No PDF URL'
                    self.log_metadata(record)
                    no_pdf += 1
                    continue
                
                success = self.download_pdf(record)
                self.log_metadata(record)
                
                if success:
                    successful += 1
                else:
                    failed += 1
                
                # Add a small delay to avoid overwhelming the server
                time.sleep(0.5)
            
            print(f"\n{'='*60}")
            print(f"Scraping completed!")
            print(f"Total records processed: {len(records)}")
            print(f"Successful downloads: {successful}")
            print(f"Failed downloads: {failed}")
            print(f"Records without PDF URL: {no_pdf}")
            print(f"PDFs saved to: {os.path.abspath(self.output_dir)}")
            print(f"Metadata saved to: {os.path.abspath(self.metadata_file)}")
            print(f"{'='*60}")
            
        except Exception as e:
            print(f"Error during scraping: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Close the browser
            if self.driver:
                print("Closing browser...")
                self.driver.quit()


if __name__ == "__main__":
    # Example usage
    scraper = SupremeCourtScraper(
        output_dir="raw_pdfs",
        metadata_file="metadata.csv"
    )
    scraper.scrape()
