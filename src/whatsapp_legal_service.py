"""
LawYaar WhatsApp Integration Service
Bridges WhatsApp messages to the LawYaar legal research RAG system
"""
import logging
import os
import sys
import asyncio
import csv
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flow import create_online_research_flow
from utils.vector_db import create_vector_db
from config import get_vector_db_config
import shelve

logger = logging.getLogger(__name__)

class LawYaarWhatsAppService:
    """Service to handle WhatsApp messages using LawYaar's legal RAG system"""
    
    def __init__(self):
        """Initialize the service with LawYaar's vector database"""
        try:
            # Initialize vector database (from your LawYaar system)
            logger.info("Initializing LawYaar vector database for WhatsApp...")
            vdb_config = get_vector_db_config()
            self.vector_db = create_vector_db()
            self.vector_db.create_or_get_collection(vdb_config.COLLECTION_NAME)
            logger.info("LawYaar vector database initialized successfully")
            
            # Store conversation history per WhatsApp user
            self.conversation_db = "lawyaar_whatsapp_chats_db"
            
            # Load PDF metadata for linking
            self.pdf_metadata = self._load_pdf_metadata()
            logger.info(f"Loaded {len(self.pdf_metadata)} PDF entries from metadata")
            
        except Exception as e:
            logger.error(f"Error initializing LawYaar WhatsApp service: {e}")
            self.vector_db = None
            self.pdf_metadata = {}
    
    def check_if_chat_exists(self, wa_id):
        """Check if a chat session exists for this WhatsApp ID"""
        with shelve.open(self.conversation_db) as chats_shelf:
            return chats_shelf.get(wa_id, None)
    
    def store_chat(self, wa_id, chat_history):
        """Store chat history for a WhatsApp ID"""
        with shelve.open(self.conversation_db, writeback=True) as chats_shelf:
            chats_shelf[wa_id] = chat_history
    
    def _load_pdf_metadata(self):
        """Load PDF URLs from metadata.csv"""
        metadata_path = Path(__file__).parent / "scraper" / "metadata.csv"
        pdf_map = {}
        
        try:
            if not metadata_path.exists():
                logger.warning(f"Metadata file not found: {metadata_path}")
                return pdf_map
            
            with open(metadata_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    case_no = row.get('Case_No', '').strip()
                    filename = row.get('Filename', '').strip()
                    pdf_url = row.get('PDF_URL', '').strip()
                    case_title = row.get('Case_Title', '').strip()
                    
                    if case_no and pdf_url:
                        # Map both case number and filename to PDF info
                        pdf_map[case_no] = {'url': pdf_url, 'title': case_title, 'case_no': case_no}
                        if filename:
                            # Remove .txt extension if present
                            base_filename = filename.replace('.txt', '').replace('.pdf', '')
                            pdf_map[base_filename] = {'url': pdf_url, 'title': case_title, 'case_no': case_no}
            
            return pdf_map
            
        except Exception as e:
            logger.error(f"Error loading PDF metadata: {e}")
            return pdf_map
    
    def _get_pdf_links_for_documents(self, document_names: list) -> list:
        """Get PDF URLs for the given document names"""
        pdf_links = []
        seen_urls = set()
        
        for doc_name in document_names:
            # Try exact match first
            if doc_name in self.pdf_metadata:
                pdf_info = self.pdf_metadata[doc_name]
                url = pdf_info['url']
                if url and url not in seen_urls:
                    pdf_links.append(pdf_info)
                    seen_urls.add(url)
                continue
            
            # Try partial match (remove .txt extension)
            base_name = doc_name.replace('.txt', '').replace('.pdf', '')
            if base_name in self.pdf_metadata:
                pdf_info = self.pdf_metadata[base_name]
                url = pdf_info['url']
                if url and url not in seen_urls:
                    pdf_links.append(pdf_info)
                    seen_urls.add(url)
        
        return pdf_links
    
    async def generate_legal_response(self, message_body: str, wa_id: str, name: str, return_metadata: bool = False):
        """
        Generate a legal research response using LawYaar's RAG system.
        
        Args:
            message_body: The user's question/query
            wa_id: WhatsApp user ID for conversation tracking
            name: User's name
            return_metadata: If True, returns dict with response and metadata; if False, returns string
            
        Returns:
            str or dict: AI-generated legal response, optionally with metadata
        """
        try:
            logger.info(f"Processing legal query from {name} ({wa_id}): {message_body[:100]}")
            
            # Check if vector DB is available
            if not self.vector_db:
                return ("I apologize, but the legal research database is currently unavailable. "
                       "Please try again later or contact support.")
            
            # Retrieve chat history (for context)
            chat_history = self.check_if_chat_exists(wa_id)
            
            # Build context from previous conversation if available
            conversation_context = ""
            if chat_history:
                # Get last 3 exchanges for context
                recent_history = chat_history[-6:] if len(chat_history) > 6 else chat_history
                conversation_context = "\n".join([
                    f"{'User' if i % 2 == 0 else 'Assistant'}: {msg.get('parts', [''])[0][:200]}"
                    for i, msg in enumerate(recent_history)
                ])
                logger.info(f"Using conversation context for {name}")
            
            # Detect language and create instruction for same-language response
            detected_language, language_instruction = self._detect_language_and_create_instruction(message_body)
            
            # Log language detection
            logger.info("="*80)
            logger.info("LANGUAGE DETECTION & TRANSLATION CHECK")
            logger.info("="*80)
            logger.info(f"Original query: {message_body}")
            logger.info(f"Detected language: {detected_language}")
            
            # IMPORTANT: If query is in Urdu, Sindhi, or Balochi, translate to English for vector search
            # (since our documents and embeddings are in English)
            search_query = message_body
            if detected_language in ['ur', 'sd', 'bl']:
                logger.info(f"✅ {detected_language.upper()} detected - will translate for vector search")
                logger.info(f"Original {detected_language} query: {message_body[:100]}")
                search_query = await self._translate_to_english(message_body, detected_language)
                logger.info(f"✅ English translation for search: {search_query}")
                logger.info(f"Translation success: Query will be searched in English")
            else:
                logger.info(f"✅ English detected - no translation needed")
                logger.info(f"Search query (same as input): {search_query}")
            
            logger.info("="*80)
            
            # Create shared state for LawYaar research flow
            shared = {
                "user_query": search_query,  # Use translated query for vector search
                "language_instruction": language_instruction,  # Add language instruction
                "vector_db": self.vector_db,
                "retrieved_chunks": [],
                "retrieval_count": 0,
                "unique_documents": [],
                "unique_document_count": 0,
                "processed_documents": [],
                "successful_documents": [],
                "failed_documents": [],
                "final_response": ""
            }
            
            # Run the LawYaar online research flow
            logger.info("Running LawYaar legal research flow...")
            online_flow = create_online_research_flow()
            await online_flow.run_async(shared)
            
            # Extract the response
            final_response = shared.get("final_response", "")
            
            if not final_response:
                logger.warning("LawYaar flow returned empty response")
                empty_response = ("I apologize, but I couldn't generate a response to your legal query. "
                                "Please try rephrasing your question or contact a legal professional.")
                # Translate error message if input was in Urdu, Sindhi, or Balochi
                if detected_language in ['ur', 'sd', 'bl']:
                    empty_response = await self._translate_to_target_language(empty_response, detected_language)
                return empty_response
            
            # Get PDF links for successful documents (new field name)
            successful_docs = shared.get("successful_documents", [])
            # Extract doc_id from processed documents
            doc_names = [doc.get('doc_id', '') for doc in successful_docs]
            pdf_links = self._get_pdf_links_for_documents(doc_names)
            
            # If return_metadata is True, return dict with full response and metadata
            if return_metadata:
                return {
                    "full_legal_response": final_response,
                    "relevant_documents": doc_names,  # Keep same key for backward compatibility
                    "pdf_links": pdf_links,
                    "document_count": len(doc_names),
                    "detected_language": detected_language
                }
            
            # Otherwise, format for WhatsApp with PDF links
            # If input was in Urdu, Sindhi, or Balochi but response is in English, translate it
            if detected_language in ['ur', 'sd', 'bl']:
                logger.info(f"Detected {detected_language} input - translating response to {detected_language}...")
                final_response = await self._translate_to_target_language(final_response, detected_language)
            
            # Format response for WhatsApp (keep it concise)
            whatsapp_response = self._format_for_whatsapp(final_response, shared, pdf_links)
            
            # Update conversation history
            new_history = chat_history if chat_history else []
            new_history.append({"role": "user", "parts": [message_body]})
            new_history.append({"role": "model", "parts": [whatsapp_response]})
            self.store_chat(wa_id, new_history)
            
            logger.info(f"Generated legal response for {name} (length: {len(whatsapp_response)} chars)")
            return whatsapp_response
            
        except Exception as e:
            logger.error(f"Error generating legal response: {e}", exc_info=True)
            error_message = ("I apologize, but I encountered an error while researching your legal question. "
                           "Please try again or contact a legal professional for assistance.")
            
            # If return_metadata is True, return dict even for errors
            if return_metadata:
                return {
                    "full_legal_response": error_message,
                    "relevant_documents": [],
                    "pdf_links": [],
                    "document_count": 0,
                    "detected_language": "en"
                }
            
            return error_message
    
    def _detect_language_and_create_instruction(self, text: str) -> tuple[str, str]:
        """
        Detect the language of input text and create instruction to respond in same language.

        Args:
            text: Input text to detect language

        Returns:
            tuple: (language_code, instruction) where language_code is 'ur' for Urdu, 'sd' for Sindhi, 'bl' for Balochi, or 'en' for English
        """
        # Use LLM for intelligent detection
        try:
            import google.generativeai as genai
            import os

            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if gemini_api_key:
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')

                detection_prompt = f"""Analyze this text and determine the primary language being used.

TEXT TO ANALYZE: "{text}"

LANGUAGE CLASSIFICATION TASK:
- If the text is primarily in ENGLISH, respond with "ENGLISH"
- If the text is primarily in URDU (even if mixed with English), respond with "URDU"
- If the text is primarily in SINDHI (even if mixed with English), respond with "SINDHI"
- If the text is primarily in BALOCHI (even if mixed with English), respond with "BALOCHI"

CONSIDER:
1. Script: Urdu/Sindhi/Balochi use Arabic script, English uses Latin
2. Context: Legal questions about Pakistan often indicate Urdu unless specified otherwise
3. Keywords: Look for language-specific terms, place names, or cultural references
4. Mixing: If text has both scripts, prioritize the non-English script
5. Linguistic patterns: Consider grammar, vocabulary, and sentence structure unique to each language

EXAMPLES:
- "What are tenant rights in Pakistan?" → ENGLISH
- "کیا کرایہ دار کے حقوق کیا ہیں؟" → URDU
- "ڪراچي ۾ ڪرائيدار جا حق ڇا آهن؟" → SINDHI
- "کِرایِداراں کے کَے حُقُوق ءَنت؟" → BALOCHI
- "Tell me about divorce laws in Urdu" → URDU (explicitly requested)
- "سنڌي قانون بابت بتاؤ" → SINDHI
- "بلوچی میں طلاق کے قوانین" → BALOCHI
- "Property dispute in Karachi" → ENGLISH (but context suggests Urdu response might be preferred)
- "میرا گھر چھین لیا گیا ہے" → URDU
- "مون کي گهر کسي چوري ڪري ورتو" → SINDHI
- "مور گَر چوری ڪَت گئی" → BALOCHI

Respond with ONLY ONE WORD: "ENGLISH", "URDU", "SINDHI", or "BALOCHI"

DETECTED LANGUAGE:"""

                response = model.generate_content(detection_prompt)
                result = response.text.strip().upper()

                # Map LLM response to our codes and instructions
                if "URDU" in result:
                    return ('ur',
                           "IMPORTANT: The user's query is in Urdu/Arabic. "
                           "You MUST respond in Urdu/Arabic script. "
                           "Provide your entire legal analysis and response in Urdu language. "
                           "اردو میں جواب دیں۔")
                elif "SINDHI" in result:
                    return ('sd',
                           "IMPORTANT: The user's query is in Sindhi. "
                           "You MUST respond in Sindhi language using Arabic script. "
                           "Provide your entire legal analysis and response in Sindhi. "
                           "سنڌي ۾ جواب ڏيو۔")
                elif "BALOCHI" in result:
                    return ('bl',
                           "IMPORTANT: The user's query is in Balochi. "
                           "You MUST respond in Balochi language using Arabic script. "
                           "Provide your entire legal analysis and response in Balochi. "
                           "بلوچی ۾ جواب ڏيو۔")
                elif "ENGLISH" in result:
                    return ('en', "Respond in clear, professional English.")
        except Exception as e:
            logger.warning(f"LLM language detection failed: {e}, falling back to script detection")

        # Fallback: Simple heuristic: check for Urdu/Arabic script characters
        urdu_arabic_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')

        if urdu_arabic_chars > len(text) * 0.2:  # If more than 20% Urdu/Arabic characters
            return ('ur',
                   "IMPORTANT: The user's query is in Urdu/Arabic. "
                   "You MUST respond in Urdu/Arabic script. "
                   "Provide your entire legal analysis and response in Urdu language. "
                   "اردو میں جواب دیں۔")
        else:
            # Default to English
            return ('en', "Respond in clear, professional English.")
    
    async def _translate_to_english(self, text: str, source_language: str) -> str:
        """
        Translate query from source language to English for vector search.
        
        Args:
            text: Query in source language
            source_language: Source language code ('ur', 'sd', 'bl')
            
        Returns:
            str: Translated query in English
        """
        try:
            import google.generativeai as genai
            import os
            
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if not gemini_api_key:
                logger.error("GEMINI_API_KEY not found - cannot translate query")
                return text  # Return original if can't translate
            
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            language_names = {
                'ur': 'Urdu',
                'sd': 'Sindhi', 
                'bl': 'Balochi'
            }
            
            language_name = language_names.get(source_language, 'Urdu')
            
            translation_prompt = f"""Translate this {language_name} legal query to English. Keep it concise and maintain the legal intent.

{language_name.upper()} QUERY:
{text}

ENGLISH TRANSLATION (only the translation, nothing else):"""
            
            logger.info(f"Translating {language_name} query to English for vector search...")
            response = model.generate_content(translation_prompt)
            english_text = response.text.strip()
            logger.info(f"Translated query: {english_text}")
            
            return english_text
            
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return text  # Fallback to original
    
    async def _translate_to_target_language(self, english_text: str, target_language: str) -> str:
        """
        Translate English legal response to target language using Gemini API.
        
        Args:
            english_text: Legal response in English
            target_language: Target language code ('ur', 'sd', 'bl')
            
        Returns:
            str: Translated text in target language
        """
        try:
            import google.generativeai as genai
            import os
            
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if not gemini_api_key:
                logger.error(f"GEMINI_API_KEY not found - cannot translate to {target_language}")
                return english_text  # Return original if can't translate
            
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            language_names = {
                'ur': 'Urdu',
                'sd': 'Sindhi',
                'bl': 'Balochi'
            }
            
            language_name = language_names.get(target_language, 'Urdu')
            
            translation_prompt = f"""Translate the following legal analysis from English to {language_name}. 
Maintain all legal terminology accuracy and preserve the structure (headings, bullet points, etc.).
Keep case citations in English but translate the rest.
Be professional and formal in {language_name}.

ENGLISH TEXT:
{english_text}

{language_name.upper()} TRANSLATION:"""
            
            logger.info(f"Translating legal response to {language_name}...")
            response = model.generate_content(translation_prompt)
            translated_text = response.text.strip()
            
            logger.info(f"✅ Translation successful ({len(translated_text)} characters)")
            return translated_text
            
        except Exception as e:
            logger.error(f"❌ Translation error: {e}")
            return english_text  # Fallback to English if translation fails
    
    def _format_for_whatsapp(self, response: str, shared: dict, pdf_links: list = None) -> str:
        """
        Format the legal response for WhatsApp.
        Keep it concise and readable on mobile.
        
        Args:
            response: The full legal response
            shared: Shared state from the research flow
            pdf_links: List of PDF link dictionaries (optional)
            
        Returns:
            str: Formatted response for WhatsApp
        """
        # Get document count for citation (use successful_documents from new pipeline)
        doc_count = len(shared.get("successful_documents", []))
        
        # Truncate very long responses for WhatsApp
        max_length = 3500  # Leave room for PDF links
        
        if len(response) > max_length:
            truncated = response[:max_length - 200]
            # Try to end at a sentence
            last_period = truncated.rfind('.')
            if last_period > max_length - 500:
                truncated = truncated[:last_period + 1]
            
            response = (f"{truncated}\n\n"
                       f"_[Response truncated for WhatsApp. {doc_count} legal cases analyzed.]_")
        else:
            # Add citation info at the end
            if doc_count > 0:
                response += f"\n\n_Based on analysis of {doc_count} relevant legal cases._"
        
        # Add PDF links section if available
        if pdf_links and len(pdf_links) > 0:
            response += "\n\n📄 *Full Case Documents:*\n"
            for i, pdf_info in enumerate(pdf_links[:5], 1):  # Limit to 5 links
                case_no = pdf_info.get('case_no', 'Case')
                url = pdf_info.get('url', '')
                if url:
                    response += f"{i}. {case_no}: {url}\n"
            
            if len(pdf_links) > 5:
                response += f"\n_Plus {len(pdf_links) - 5} more case documents_"
        
        return response


# Singleton instance
_lawyaar_service = None

def get_lawyaar_whatsapp_service():
    """Get or create the LawYaar WhatsApp service singleton"""
    global _lawyaar_service
    if _lawyaar_service is None:
        _lawyaar_service = LawYaarWhatsAppService()
    return _lawyaar_service
