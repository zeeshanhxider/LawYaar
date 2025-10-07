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


def _is_legal_query(message: str) -> str:
    """
    Classify a message into: LEGAL, CHITCHAT, or IRRELEVANT.
    
    Uses Gemini to quickly classify the message intent.
    
    Args:
        message: The user's message
        
    Returns:
        str: "LEGAL", "CHITCHAT", or "IRRELEVANT"
    """
    message_lower = message.lower().strip()
    
    # Quick keyword check for obvious greetings/chitchat
    chitchat_keywords = [
        'hi', 'hello', 'hey', 'assalam', 'salam', 'greetings',
        'thanks', 'thank you', 'ok', 'okay', 'bye', 'goodbye',
        'how are you', 'what is your name', 'who are you',
        'good morning', 'good afternoon', 'good evening'
    ]
    
    # If message is very short and matches chitchat, skip LLM call
    if len(message_lower) < 20 and any(keyword in message_lower for keyword in chitchat_keywords):
        logger.info(f"Quick chitchat detection: {message[:30]}")
        return "CHITCHAT"
    
    # For ambiguous cases, use LLM to classify
    try:
        from utils.call_llm import call_llm
        
        classification_prompt = f"""You are a message classifier for a Pakistani legal assistant chatbot.

USER MESSAGE: {message}

TASK: Classify this message into ONE category:

A) LEGAL - Questions about Pakistani law, Supreme Court cases, legal rights, procedures, bail, sentencing, contracts, property law, family law, criminal law, constitutional law, etc.

B) CHITCHAT - Greetings, thanks, small talk (hi, hello, how are you, etc.)

C) IRRELEVANT - Topics completely unrelated to law (weather, sports, recipes, jokes, math problems, movie recommendations, etc.)

IMPORTANT: Be strict about what counts as LEGAL. Only classify as LEGAL if it's genuinely related to law or legal matters.

Respond with ONLY one word: "LEGAL", "CHITCHAT", or "IRRELEVANT"

RESPONSE:"""
        
        result = call_llm(classification_prompt).strip().upper()
        
        # Extract classification
        if "LEGAL" in result:
            classification = "LEGAL"
        elif "CHITCHAT" in result:
            classification = "CHITCHAT"
        elif "IRRELEVANT" in result:
            classification = "IRRELEVANT"
        else:
            # Default to LEGAL to be safe
            classification = "LEGAL"
        
        logger.info(f"Message classification: {classification} - {message[:50]}")
        return classification
        
    except Exception as e:
        logger.error(f"Error classifying message: {e}")
        # Default to LEGAL to be safe (better to over-search than miss queries)
        return "LEGAL"


def _handle_chitchat(message: str, wa_id: str, name: str) -> str:
    """
    Generate a friendly conversational response for non-legal messages.
    
    Args:
        message: The user's message
        wa_id: WhatsApp ID
        name: User's name
        
    Returns:
        str: Friendly conversational response
    """
    try:
        # Get chat history for context
        chat_history = check_if_chat_exists(wa_id)
        
        from utils.call_llm import call_llm
        
        chitchat_prompt = f"""You are a friendly Pakistani legal assistant chatbot on WhatsApp named "LawYaar".

USER: {name}
MESSAGE: {message}

Generate a warm, brief, conversational response (2-3 sentences max). 

Guidelines:
- Be friendly and professional
- If it's a greeting, greet back and offer help with legal questions
- If it's thanks, acknowledge and offer further assistance
- Keep it SHORT (this is WhatsApp)
- Use emojis sparingly 😊

RESPONSE:"""
        
        chitchat_response = call_llm(chitchat_prompt).strip()
        
        # Store in chat history
        new_history = chat_history if chat_history else []
        new_history.append({"role": "user", "parts": [message]})
        new_history.append({"role": "model", "parts": [chitchat_response]})
        store_chat(wa_id, new_history)
        
        logger.info(f"✅ Chitchat response generated for {name}")
        return chitchat_response
        
    except Exception as e:
        logger.error(f"Error generating chitchat response: {e}")
        # Fallback responses
        detected_lang = _detect_language(message)
        if detected_lang == 'ur':
            return "السلام علیکم! میں LawYaar ہوں، آپ کا قانونی معاون 😊 میں آپ کی کیسے مدد کر سکتا ہوں؟"
        return "Hello! I'm LawYaar, your legal assistant 😊 How can I help you with legal questions today?"


def _handle_irrelevant(message: str, wa_id: str, name: str) -> str:
    """
    Politely decline irrelevant (non-legal) queries.
    
    Args:
        message: The user's message
        wa_id: WhatsApp ID
        name: User's name
        
    Returns:
        str: Polite rejection message
    """
    # Detect language for appropriate response
    detected_lang = _detect_language(message)
    
    # Store in chat history
    try:
        chat_history = check_if_chat_exists(wa_id)
        new_history = chat_history if chat_history else []
    except:
        new_history = []
    
    if detected_lang == 'ur':
        response = (
            "معذرت! 😊 میں LawYaar ہوں - پاکستان کے قانونی معاملات میں مہارت رکھنے والا \n"
            "میں صرف قانونی سوالات کا جواب دے سکتا ہوں جیسے:\n"
            "• ضمانت اور سزا\n"
            "• سپریم کورٹ کے فیصلے\n"
            "• قانونی حقوق اور طریقہ کار\n\n"
            "براہ کرم کوئی قانونی سوال پوچھیں! ⚖️"
        )
    else:
        response = (
            "I apologize! 😊 I'm LawYaar - a legal assistant specializing in Pakistani law.\n\n"
            "I can only help with legal questions such as:\n"
            "• Bail and sentencing matters\n"
            "• Supreme Court case law\n"
            "• Legal rights and procedures\n\n"
            "Please ask me a legal question! ⚖️"
        )
    
    # Store in chat history
    try:
        new_history.append({"role": "user", "parts": [message]})
        new_history.append({"role": "model", "parts": [response]})
        store_chat(wa_id, new_history)
    except Exception as e:
        logger.error(f"Error storing irrelevant query history: {e}")
    
    logger.info(f"🚫 Irrelevant query rejected for {name}: {message[:50]}")
    return response


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
        
        # Run async function in a thread-safe way
        try:
            # Check if we're in an async context
            try:
                asyncio.get_running_loop()
                # We're in an async context, use thread executor
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        service.generate_legal_response(message, wa_id, name)
                    )
                    context = future.result(timeout=120)
            except RuntimeError:
                # No running loop, safe to use asyncio.run directly
                context = asyncio.run(
                    service.generate_legal_response(message, wa_id, name)
                )
        except Exception as e:
            logger.error(f"Error running async context retrieval: {e}")
            raise
        
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
    1. Check if message is a legal query (filter greetings/chitchat)
    2. Run full legal research pipeline (Classification → Retrieval → Pruning → Reading → Aggregation)
    3. Create friendly summary using Gemini
    4. Append full legal research details
    5. Add PDF links at the end
    
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
        
        # ✨ PRE-FILTER: Classify message type (LEGAL, CHITCHAT, IRRELEVANT, or PDF_REQUEST)
        
        # First check if this is a response to PDF offer
        chat_history = check_if_chat_exists(wa_id)
        if chat_history and len(chat_history) > 0:
            last_bot_message = None
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    last_bot_message = msg
                    break
            
            # Check if user is responding to PDF offer
            if last_bot_message and _is_pdf_request(message):
                logger.info(f"📄 PDF request detected from {name}")
                research_data = last_bot_message.get('research_data', {})
                
                # Get language before PDF generation
                detected_lang = research_data.get('detected_language', 'en')
                
                # Generate PDF
                pdf_path = generate_pdf_report(wa_id, name, research_data)
                
                if pdf_path:
                    if detected_lang == 'ur':
                        return {
                            "type": "pdf_response",
                            "pdf_path": pdf_path,
                            "message": "بہترین! میں آپ کے لیے تفصیلی رپورٹ تیار کر رہا ہوں۔ یہ رپورٹ تمام کیسز کی تفصیلات، حوالہ جات اور لنکس پر مشتمل ہے۔ 📄"
                        }
                    else:
                        return {
                            "type": "pdf_response",
                            "pdf_path": pdf_path,
                            "message": "Great! I'm preparing your detailed report with all case citations and links. 📄"
                        }
                else:
                    if detected_lang == 'ur':
                        return "معذرت! PDF رپورٹ بنانے میں خرابی ہوئی۔ براہ کرم دوبارہ کوشش کریں۔"
                    else:
                        return "I apologize! There was an error generating the PDF report. Please try again."
        
        # Now proceed with normal classification
        message_type = _is_legal_query(message)
        
        if message_type == "CHITCHAT":
            logger.info(f"💬 Chitchat detected: {message[:50]}... Responding conversationally")
            return _handle_chitchat(message, wa_id, name)
        elif message_type == "IRRELEVANT":
            logger.info(f"🚫 Irrelevant query detected: {message[:50]}... Politely declining")
            return _handle_irrelevant(message, wa_id, name)
        
        # message_type == "LEGAL" - proceed with legal research
        logger.info(f"⚖️ Legal query detected: {message[:50]}... Running research pipeline")
        
        # Run full legal research pipeline with metadata
        service = get_lawyaar_service()
        
        # Use asyncio.run() which creates a fresh event loop - handles thread safety
        import nest_asyncio
        try:
            # Try to enable nested event loops (needed for some environments)
            nest_asyncio.apply()
        except:
            pass  # nest_asyncio not available, that's ok
        
        # Run async function in a thread-safe way
        try:
            # Check if we're in an async context
            try:
                asyncio.get_running_loop()
                # We're in an async context, use thread executor
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        service.generate_legal_response(message, wa_id, name, return_metadata=True)
                    )
                    research_data = future.result(timeout=180)
            except RuntimeError:
                # No running loop, safe to use asyncio.run directly
                research_data = asyncio.run(
                    service.generate_legal_response(message, wa_id, name, return_metadata=True)
                )
        except Exception as e:
            logger.error(f"Error running async research: {e}")
            raise
        
        # Safety check: ensure research_data is a dict
        if not isinstance(research_data, dict):
            logger.error(f"❌ Expected dict from generate_legal_response, got {type(research_data)}: {research_data}")
            # If it's a string error message, return it
            if isinstance(research_data, str):
                return research_data
            # Otherwise return generic error
            return "I apologize, but I encountered an error while researching your legal question. Please try again."
        
        # Extract research components
        full_legal_response = research_data.get("full_legal_response", "")
        pdf_links = research_data.get("pdf_links", [])
        doc_count = research_data.get("document_count", 0)
        detected_language = research_data.get("detected_language", "en")
        
        if not full_legal_response:
            logger.warning("Empty legal research response")
            return "I apologize, but I couldn't generate a response to your legal query. Please try rephrasing."
        
        # Check if no relevant cases were found
        no_cases_found = (
            doc_count == 0 or
            "could not find any relevant legal cases" in full_legal_response.lower() or
            "apologize" in full_legal_response.lower() and "could not find" in full_legal_response.lower()
        )
        
        # Create VOICE-OPTIMIZED dense summary (for illiterate users - no citations)
        from utils.call_llm import call_llm
        
        voice_summary_prompt = f"""You are a friendly legal assistant helping an illiterate user via WhatsApp voice message.

YOUR TASK: Create a DENSE, COMPREHENSIVE VOICE SUMMARY that:
- DIRECTLY ANSWERS the user's legal question in simple, spoken language
- Includes ALL important legal information from the research
- Explains the legal principles, procedures, and rights clearly
- Uses conversational tone suitable for audio (as if talking to a friend)
- NO case numbers, NO citations, NO metadata (user can't see/read them in voice)
- Keep it focused but comprehensive (400-500 words for voice)
- Use examples and analogies when helpful
- In {'Urdu' if detected_language == 'ur' else 'English'}

USER'S QUESTION: {message}

DETAILED LEGAL RESEARCH WITH ALL FINDINGS:
{full_legal_response}

IMPORTANT: Synthesize ALL the key legal information into a natural spoken explanation. Imagine you're explaining to someone who cannot read. Be thorough but natural.

VOICE SUMMARY:"""
        
        try:
            voice_summary = call_llm(voice_summary_prompt).strip()
        except Exception as e:
            logger.error(f"⚠️ LLM API error generating voice summary: {e}")
            # Fallback: Use first two paragraphs of legal response
            paragraphs = full_legal_response.split('\n\n')
            if len(paragraphs) >= 2:
                voice_summary = '\n\n'.join(paragraphs[:2])
            elif paragraphs:
                voice_summary = paragraphs[0]
            else:
                voice_summary = "Here's what I found from the legal research:"
        
        # Add PDF offer at the end of voice summary
        if detected_language == 'ur':
            pdf_offer = f"\n\nاگر آپ مکمل تفصیلی رپورٹ چاہتے ہیں جس میں تمام کیسز کی تفصیلات اور لنکس ہوں، تو براہ کرم 'ہاں' یا 'جی' بھیجیں۔ میں آپ کو ایک تفصیلی PDF دستاویز بھیج دوں گا۔"
        else:
            pdf_offer = f"\n\nIf you'd like a detailed report with all case citations and links, please reply with 'yes' or 'haan'. I'll send you a comprehensive PDF document."
        
        voice_summary_with_offer = voice_summary + pdf_offer
        
        # Create friendly summary for backward compatibility (if needed)
        friendly_summary = voice_summary
        
        # Store research data and prepare for parallel PDF generation
        # PDF will be generated in background while user listens to voice
        try:
            chat_history = check_if_chat_exists(wa_id)
            if not chat_history:
                chat_history = []
            
            # Store the full research data in chat context
            research_context = {
                "type": "pending_pdf_request",
                "query": message,
                "full_legal_response": full_legal_response,
                "pdf_links": pdf_links,
                "doc_count": doc_count,
                "detected_language": detected_language,
                "voice_summary": voice_summary
            }
            
            # Add to chat history
            chat_history.append({"role": "user", "parts": [message]})
            chat_history.append({
                "role": "model", 
                "parts": [voice_summary],  # Just voice summary, no PDF offer here
                "research_data": research_context  # Store for PDF generation
            })
            store_chat(wa_id, chat_history)
            
        except Exception as e:
            logger.error(f"Error storing research context: {e}")
        
        # Return voice summary WITHOUT PDF offer (offer will be sent as separate text)
        # Also return research data for parallel PDF generation
        logger.info(f"✅ Voice-optimized summary complete: {len(voice_summary)} characters")
        
        return {
            "type": "voice_with_pdf_prep",
            "voice_summary": voice_summary,
            "research_data": research_context,
            "detected_language": detected_language
        }
        
    except Exception as e:
        logger.error(f"❌ Critical error in generate_response: {e}", exc_info=True)
        # Never expose internal errors to user
        try:
            detected_lang = _detect_language(message) if message else 'en'
        except:
            detected_lang = 'en'
        
        if detected_lang == 'ur':
            return (
                "معذرت! 😔 مجھے آپ کے سوال کا جواب دینے میں دشواری ہو رہی ہے۔\n\n"
                "براہ کرم:\n"
                "• اپنا سوال دوبارہ لکھیں\n"
                "• یا کچھ دیر بعد کوشش کریں\n\n"
                "شکریہ! 🙏"
            )
        return (
            "I apologize! 😔 I'm having trouble processing your question.\n\n"
            "Please try:\n"
            "• Rephrasing your question\n"
            "• Asking again in a few moments\n\n"
            "Thank you for your patience! 🙏"
        )


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


def _is_pdf_request(message: str) -> bool:
    """
    Check if user is requesting the detailed PDF report.
    
    Args:
        message: User's message
        
    Returns:
        bool: True if user wants PDF, False otherwise
    """
    message_lower = message.lower().strip()
    
    # English affirmatives
    english_yes = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'send', 'please', 'want', 
                   'give', 'show', 'detailed', 'full', 'complete', 'pdf', 'report', 'document']
    
    # Urdu affirmatives (romanized and script)
    urdu_yes = ['haan', 'haa', 'han', 'ji', 'jee', 'zaroor', 'zarur', 
                'bhejo', 'bhej do', 'chahiye', 'چاہیے', 'ہاں', 'جی', 'ضرور', 'بھیجو']
    
    # Check if message contains any affirmative
    for word in english_yes + urdu_yes:
        if word in message_lower:
            return True
    
    # If message is very short (1-3 words) and doesn't contain negatives, assume yes
    words = message_lower.split()
    if len(words) <= 3:
        negatives = ['no', 'nah', 'nope', 'dont', "don't", 'nahi', 'nhi', 'نہیں', 'نہ']
        has_negative = any(neg in message_lower for neg in negatives)
        if not has_negative:
            return True
    
    return False


def _is_pdf_rejection(message: str) -> bool:
    """
    Check if user is rejecting/declining the PDF offer.
    
    Args:
        message: User's message
        
    Returns:
        bool: True if user doesn't want PDF, False otherwise
    """
    message_lower = message.lower().strip()
    
    # English negatives
    english_no = ['no', 'nah', 'nope', 'not', 'dont', "don't", 'never', 'nvm', 
                  'skip', 'pass', 'later', 'maybe later']
    
    # Urdu negatives (romanized and script)
    urdu_no = ['nahi', 'nhi', 'na', 'naa', 'zaroorat nahi', 'baad mein',
               'نہیں', 'نہ', 'نا', 'ضرورت نہیں', 'بعد میں']
    
    # Check if message contains any negative
    for word in english_no + urdu_no:
        if word in message_lower:
            return True
    
    return False


def _handle_pdf_rejection(wa_id: str, detected_language: str) -> str:
    """
    Handle when user declines the PDF offer.
    
    Args:
        wa_id: WhatsApp user ID
        detected_language: Language of the conversation
        
    Returns:
        str: Friendly acknowledgment message
    """
    # Update chat history to mark PDF as declined
    try:
        chat_history = check_if_chat_exists(wa_id)
        if chat_history and len(chat_history) > 0:
            # Find and update the last message with pending PDF
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    msg['research_data']['pdf_declined'] = True
                    break
            store_chat(wa_id, chat_history)
    except Exception as e:
        logger.error(f"Error updating PDF rejection status: {e}")
    
    # Return friendly message
    if detected_language == 'ur':
        return (
            "ٹھیک ہے، کوئی بات نہیں! 😊\n\n"
            "اگر آپ کو کوئی اور قانونی سوال ہو تو بے جھجھک پوچھیں۔ "
            "میں یہاں آپ کی مدد کے لیے ہوں! ⚖️"
        )
    else:
        return (
            "No problem at all! 😊\n\n"
            "If you have any other legal questions, feel free to ask. "
            "I'm here to help! ⚖️"
        )


def generate_pdf_report(wa_id: str, name: str, research_data: dict) -> str:
    """
    Generate a detailed PDF report with full legal analysis.
    
    Args:
        wa_id: WhatsApp user ID
        name: User's name
        research_data: Stored research data from previous query
        
    Returns:
        str: Path to generated PDF file
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_RIGHT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import tempfile
        from datetime import datetime
        
        # Register Urdu-compatible font (Arial supports Arabic/Urdu)
        try:
            # Use system Arial font which supports Urdu/Arabic
            font_path = r"C:\Windows\Fonts\arial.ttf"
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('ArialUnicode', font_path))
                urdu_font = 'ArialUnicode'
                logger.info("✅ Registered Arial font for Urdu support")
            else:
                # Fallback to Helvetica
                urdu_font = 'Helvetica'
                logger.warning("⚠️ Arial font not found, using Helvetica fallback")
        except Exception as font_error:
            urdu_font = 'Helvetica'
            logger.warning(f"⚠️ Font registration failed: {font_error}, using Helvetica fallback")
        
        # Extract research data
        query = research_data.get('query', 'Legal Query')
        full_legal_response = research_data.get('full_legal_response', '')
        pdf_links = research_data.get('pdf_links', [])
        doc_count = research_data.get('doc_count', 0)
        detected_language = research_data.get('detected_language', 'en')
        voice_summary = research_data.get('voice_summary', '')
        
        # Create PDF file
        temp_dir = tempfile.gettempdir()
        pdf_filename = f"LawYaar_Report_{wa_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(temp_dir, pdf_filename)
        
        # Create PDF document
        doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                              rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        # Container for PDF elements
        story = []
        
        # Styles with Urdu font support
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name='Justify',
            alignment=TA_JUSTIFY,
            fontName=urdu_font,
            fontSize=11,
            leading=14
        ))
        styles.add(ParagraphStyle(
            name='UrduNormal',
            parent=styles['Normal'],
            fontName=urdu_font,
            fontSize=11,
            alignment=TA_RIGHT  # Right-aligned for Urdu text
        ))
        
        # Title
        title_text = "LawYaar Legal Research Report"
        title = Paragraph(title_text, styles['Title'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # Metadata
        meta_data = f"""
        <b>Generated for:</b> {name}<br/>
        <b>Date:</b> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br/>
        <b>Cases Analyzed:</b> {doc_count}<br/>
        <b>Language:</b> {'Urdu/English' if detected_language == 'ur' else 'English'}
        """
        story.append(Paragraph(meta_data, styles['Normal']))
        story.append(Spacer(1, 12))
        
        # User Query
        story.append(Paragraph("<b>Your Legal Query:</b>", styles['Heading2']))
        # Escape XML special characters in query
        from xml.sax.saxutils import escape
        query_escaped = escape(query)
        story.append(Paragraph(query_escaped, styles['Justify']))
        story.append(Spacer(1, 12))
        
        # Summary
        story.append(Paragraph("<b>Executive Summary:</b>", styles['Heading2']))
        # Escape and convert markdown to simple text for PDF
        summary_escaped = escape(voice_summary)
        # Simple markdown conversion (bold only)
        import re
        # Replace **text** with <b>text</b>
        summary_escaped = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', summary_escaped)
        # Replace *text* with <i>text</i>
        summary_escaped = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', summary_escaped)
        story.append(Paragraph(summary_escaped, styles['Justify']))
        story.append(Spacer(1, 12))
        
        story.append(PageBreak())
        
        # Detailed Legal Analysis
        story.append(Paragraph("<b>Detailed Legal Analysis:</b>", styles['Heading2']))
        story.append(Spacer(1, 12))
        
        # Escape and convert markdown to PDF-friendly format
        legal_text = escape(full_legal_response)
        # Replace **text** with <b>text</b> properly
        legal_text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', legal_text)
        # Replace newlines with breaks
        legal_text = legal_text.replace('\n', '<br/>')
        
        # Split into paragraphs
        for para in legal_text.split('<br/><br/>'):
            if para.strip():
                story.append(Paragraph(para, styles['Justify']))
                story.append(Spacer(1, 6))
        
        story.append(PageBreak())
        
        # Case References with Links
        if pdf_links and len(pdf_links) > 0:
            story.append(Paragraph("<b>Case Documents & References:</b>", styles['Heading2']))
            story.append(Spacer(1, 12))
            
            for i, pdf_info in enumerate(pdf_links, 1):
                case_no = pdf_info.get('case_no', 'Case')
                case_title = pdf_info.get('title', '')
                url = pdf_info.get('url', '')
                
                case_text = f"<b>{i}. {case_no}</b>"
                if case_title:
                    case_text += f": {case_title}"
                if url:
                    case_text += f"<br/><a href='{url}'>{url}</a>"
                
                story.append(Paragraph(case_text, styles['Normal']))
                story.append(Spacer(1, 6))
        
        # Footer
        story.append(Spacer(1, 24))
        footer_text = """
        <i>This report was generated by LawYaar, an AI-powered legal research assistant. 
        While we strive for accuracy, please consult with a qualified legal professional 
        for advice specific to your situation.</i>
        """
        story.append(Paragraph(footer_text, styles['Normal']))
        
        # Build PDF
        doc.build(story)
        
        logger.info(f"✅ PDF report generated: {pdf_path}")
        return pdf_path
        
    except Exception as e:
        logger.error(f"❌ Error generating PDF report: {e}", exc_info=True)
        return None


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
