"""
Gemini Service - Generates responses using LawYaar's legal research system.
This service acts as a bridge between WhatsApp messages and LawYaar's RAG system.
Maintains conversational context per user for a more natural chat experience.
"""

import logging
import asyncio
import sys
import os
import shelve
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from project root
env_path = Path(__file__).parent.parent.parent.parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Add src directory to path to import LawYaar modules
src_path = str(Path(__file__).parent.parent.parent.parent.parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

logger = logging.getLogger(__name__)

# Configure Gemini for conversational AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Model configuration for natural conversation
generation_config = {
    "temperature": 0.8,  # Slightly creative but still focused
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 2048,  # Concise for WhatsApp
}

# Initialize conversational model
conversation_model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config=generation_config,
)

# Import LawYaar WhatsApp service
try:
    from whatsapp_legal_service import LawYaarWhatsAppService
    _lawyaar_service = None
    
    def get_lawyaar_service():
        """Get or create the LawYaar WhatsApp service singleton."""
        global _lawyaar_service
        if _lawyaar_service is None:
            _lawyaar_service = LawYaarWhatsAppService()
        return _lawyaar_service
    
    LAWYAAR_AVAILABLE = True
    logger.info("✅ LawYaar legal research system loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ LawYaar system not available: {e}")
    LAWYAAR_AVAILABLE = False


# Chat history management (like example.py)
def check_if_chat_exists(wa_id):
    """Check if a chat session exists for this WhatsApp ID"""
    try:
        with shelve.open("chats_db") as chats_shelf:
            return chats_shelf.get(wa_id, None)
    except Exception as e:
        logger.error(f"Error checking chat existence: {e}")
        return None


def store_chat(wa_id, chat_history):
    """Store chat history for a WhatsApp ID"""
    try:
        with shelve.open("chats_db", writeback=True) as chats_shelf:
            chats_shelf[wa_id] = chat_history
    except Exception as e:
        logger.error(f"Error storing chat: {e}")


def get_legal_context(message, wa_id, name):
    """
    Get relevant legal context from LawYaar RAG system.
    
    Args:
        message: User's question
        wa_id: WhatsApp ID
        name: User's name
        
    Returns:
        str: Relevant legal context or empty string
    """
    if not LAWYAAR_AVAILABLE:
        return ""
    
    try:
        service = get_lawyaar_service()
        
        # Run async function in sync context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        service.generate_legal_response(message, wa_id, name)
                    )
                    context = future.result(timeout=120)
            else:
                context = loop.run_until_complete(
                    service.generate_legal_response(message, wa_id, name)
                )
        except RuntimeError:
            context = asyncio.run(
                service.generate_legal_response(message, wa_id, name)
            )
        
        return context
    except Exception as e:
        logger.error(f"Error getting legal context: {e}")
        return ""


def generate_response(message, wa_id, name):
    """
    Generate a HYBRID response: Friendly summary + Full legal research + PDF links.
    
    Uses LawYaar's multi-agent legal research pipeline (same as CLI) but wraps it
    in a conversational, easy-to-understand format for WhatsApp users.
    
    Architecture:
    1. Run full legal research pipeline (Classification → Retrieval → Pruning → Reading → Aggregation)
    2. Create friendly summary using Gemini
    3. Append full legal research details
    4. Add PDF links at the end
    
    Args:
        message (str): The user's legal query
        wa_id (str): WhatsApp ID of the user
        name (str): Name of the user
        
    Returns:
        str: Hybrid response (friendly summary + legal research + PDF links)
    """
    try:
        logger.info(f"🔍 Processing hybrid response for {name}: {message[:100]}...")
        
        if not LAWYAAR_AVAILABLE:
            logger.error("❌ LawYaar legal research system not available")
            return ("I apologize, but the legal research system is currently unavailable. "
                   "Please try again later.")
        
        # Run full legal research pipeline with metadata
        service = get_lawyaar_service()
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        service.generate_legal_response(message, wa_id, name, return_metadata=True)
                    )
                    research_data = future.result(timeout=180)
            else:
                research_data = loop.run_until_complete(
                    service.generate_legal_response(message, wa_id, name, return_metadata=True)
                )
        except RuntimeError:
            research_data = asyncio.run(
                service.generate_legal_response(message, wa_id, name, return_metadata=True)
            )
        
        # Extract research components
        full_legal_response = research_data.get("full_legal_response", "")
        pdf_links = research_data.get("pdf_links", [])
        doc_count = research_data.get("document_count", 0)
        detected_language = research_data.get("detected_language", "en")
        
        if not full_legal_response:
            logger.warning("Empty legal research response")
            return "I apologize, but I couldn't generate a response to your legal query. Please try rephrasing."
        
        # Create friendly summary using Gemini
        summary_prompt = f"""You are a friendly legal assistant on WhatsApp. You just completed a detailed legal research.
        
YOUR TASK: Create a SHORT, FRIENDLY, EASY-TO-UNDERSTAND summary (2-3 paragraphs) that:
- Directly answers the user's question in simple language
- Highlights the most important points
- Uses a conversational, helpful tone
- Keeps it brief (this is WhatsApp!)
- Uses emojis sparingly to be personable 😊

USER'S QUESTION: {message}

DETAILED LEGAL RESEARCH:
{full_legal_response[:2000]}...

Write a friendly summary in {'Urdu' if detected_language == 'ur' else 'English'}:"""
        
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            summary_response = model.generate_content(summary_prompt)
            friendly_summary = summary_response.text.strip()
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            # Fallback to first paragraph of legal response
            friendly_summary = full_legal_response.split('\n\n')[0] if full_legal_response else "Here's what I found..."
        
        # Build hybrid response
        hybrid_response = f"{friendly_summary}\n\n"
        hybrid_response += f"━━━━━━━━━━━━━━━━━━━━\n"
        hybrid_response += f"� *Detailed Legal Analysis*\n"
        hybrid_response += f"━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Add truncated legal research (limit for WhatsApp)
        max_legal_length = 2000
        if len(full_legal_response) > max_legal_length:
            truncated_legal = full_legal_response[:max_legal_length]
            last_period = truncated_legal.rfind('.')
            if last_period > max_legal_length - 200:
                truncated_legal = truncated_legal[:last_period + 1]
            hybrid_response += f"{truncated_legal}\n\n_[Full analysis truncated]_"
        else:
            hybrid_response += full_legal_response
        
        # Add PDF links
        if pdf_links and len(pdf_links) > 0:
            hybrid_response += "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            hybrid_response += "📄 *Full Case Documents*\n"
            hybrid_response += "━━━━━━━━━━━━━━━━━━━━\n"
            for i, pdf_info in enumerate(pdf_links[:5], 1):
                case_no = pdf_info.get('case_no', 'Case')
                url = pdf_info.get('url', '')
                if url:
                    hybrid_response += f"{i}. {case_no}\n   {url}\n\n"
            
            if len(pdf_links) > 5:
                hybrid_response += f"_Plus {len(pdf_links) - 5} more documents_\n"
        
        # Add footer
        hybrid_response += f"\n_Analyzed {doc_count} legal cases_"
        
        logger.info(f"✅ Hybrid response complete: {len(hybrid_response)} characters")
        return hybrid_response
        
    except Exception as e:
        logger.error(f"❌ Error generating hybrid response: {e}", exc_info=True)
        detected_lang = _detect_language(message) if message else 'en'
        if detected_lang == 'ur':
            return "معذرت، مجھے ایک مسئلہ کا سامنا کرنا پڑا 😔 براہ کرم دوبارہ کوشش کریں۔"
        return "I apologize, but I encountered an error 😔 Please try again."


def _detect_language(text: str) -> str:
    """
    Detect if text is in Urdu/Arabic or English.
    
    Args:
        text: Input text to detect language
        
    Returns:
        str: 'ur' for Urdu/Arabic, 'en' for English
    """
    # Count Urdu/Arabic script characters
    urdu_arabic_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
    
    # If more than 20% Urdu/Arabic characters, consider it Urdu
    if len(text) > 0 and urdu_arabic_chars > len(text) * 0.2:
        return 'ur'
    return 'en'


def _is_urdu_text(text: str) -> bool:
    """
    Check if text is already in Urdu.
    
    Args:
        text: Text to check
        
    Returns:
        bool: True if text is in Urdu, False otherwise
    """
    urdu_arabic_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
    return len(text) > 0 and urdu_arabic_chars > len(text) * 0.2


def _translate_to_urdu(english_text: str) -> str:
    """
    Translate English text to Urdu using Gemini API.
    
    Args:
        english_text: Text in English
        
    Returns:
        str: Translated text in Urdu
    """
    try:
        import google.generativeai as genai
        import os
        
        gemini_api_key = os.getenv('GEMINI_API_KEY')
        if not gemini_api_key:
            logger.error("GEMINI_API_KEY not found - cannot translate to Urdu")
            return english_text  # Return original if can't translate
        
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        translation_prompt = f"""Translate the following legal analysis from English to Urdu.
Maintain all legal terminology accuracy and preserve the structure (headings, bullet points, etc.).
Keep case citations and legal terms in English but translate explanations to Urdu.
Be professional and formal in Urdu.
Use proper Urdu script (اردو).

ENGLISH TEXT:
{english_text}

URDU TRANSLATION (اردو ترجمہ):"""
        
        logger.info("Translating to Urdu with Gemini...")
        response = model.generate_content(translation_prompt)
        urdu_text = response.text.strip()
        
        logger.info(f"✅ Translation successful")
        return urdu_text
        
    except Exception as e:
        logger.error(f"❌ Translation error: {e}")
        return english_text  # Fallback to English if translation fails
