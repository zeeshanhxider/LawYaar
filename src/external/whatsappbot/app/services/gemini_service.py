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
    
    # For ambiguous cases, use Gemini to classify
    try:
        classification_prompt = f"""You are a message classifier for a Pakistani legal assistant chatbot.

USER MESSAGE: {message}

TASK: Classify this message into ONE category:

A) LEGAL - Questions about Pakistani law, Supreme Court cases, legal rights, procedures, bail, sentencing, contracts, property law, family law, criminal law, constitutional law, etc.

B) CHITCHAT - Greetings, thanks, small talk (hi, hello, how are you, etc.)

C) IRRELEVANT - Topics completely unrelated to law (weather, sports, recipes, jokes, math problems, movie recommendations, etc.)

IMPORTANT: Be strict about what counts as LEGAL. Only classify as LEGAL if it's genuinely related to law or legal matters.

Respond with ONLY one word: "LEGAL", "CHITCHAT", or "IRRELEVANT"

RESPONSE:"""
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(classification_prompt)
        result = response.text.strip().upper()
        
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
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(chitchat_prompt)
        chitchat_response = response.text.strip()
        
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
        
        # ✨ PRE-FILTER: Classify message type (LEGAL, CHITCHAT, or IRRELEVANT)
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
        
        # Check if no relevant cases were found
        no_cases_found = (
            doc_count == 0 or
            "could not find any relevant legal cases" in full_legal_response.lower() or
            "apologize" in full_legal_response.lower() and "could not find" in full_legal_response.lower()
        )
        
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
            logger.error(f"⚠️ Gemini API error generating summary: {e}")
            # Fallback: Use first two paragraphs of legal response
            paragraphs = full_legal_response.split('\n\n')
            if len(paragraphs) >= 2:
                friendly_summary = '\n\n'.join(paragraphs[:2])
            elif paragraphs:
                friendly_summary = paragraphs[0]
            else:
                friendly_summary = "Here's what I found from the legal research:"
        
        # Build hybrid response starting with friendly summary
        hybrid_response = f"{friendly_summary}"
        
        # Only add detailed analysis section if cases were found
        if not no_cases_found:
            hybrid_response += "\n\n"
            hybrid_response += f"━━━━━━━━━━━━━━━━━━━━\n"
            hybrid_response += f"⚖️ *Detailed Legal Analysis*\n"
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
        
        # Add PDF links (only if cases were found)
        if pdf_links and len(pdf_links) > 0 and not no_cases_found:
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
        
        # Add footer (only if cases were found)
        if not no_cases_found and doc_count > 0:
            hybrid_response += f"\n_Analyzed {doc_count} legal cases_"
        
        logger.info(f"✅ Hybrid response complete: {len(hybrid_response)} characters")
        return hybrid_response
        
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
