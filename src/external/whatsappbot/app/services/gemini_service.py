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
    Generate a conversational response using Gemini AI with LawYaar RAG.
    Maintains conversation history per user for natural, context-aware chat.
    Automatically detects and responds in the same language as input.
    
    Args:
        message (str): The user's message text (transcribed from voice or text message)
        wa_id (str): WhatsApp ID of the user
        name (str): Name of the user
        
    Returns:
        str: Generated response in the same language as input
    """
    try:
        # Detect input language first
        detected_language = _detect_language(message)
        logger.info(f"🌐 Detected language: {'Urdu' if detected_language == 'ur' else 'English'}")
        
        # Check if there is already a chat history for this user
        chat_history = check_if_chat_exists(wa_id)
        
        # If a chat doesn't exist, create one with system instructions
        if chat_history is None:
            logger.info(f"💬 Creating new chat for {name} with wa_id {wa_id}")
            chat_history = []
            
            # Start a new chat session
            chat = conversation_model.start_chat(history=chat_history)
            
            # Get legal context from LawYaar RAG
            legal_context = get_legal_context(message, wa_id, name) if LAWYAAR_AVAILABLE else ""
            
            # Create system instruction based on detected language
            if detected_language == 'ur':
                system_message = (
                    f"آپ ایک مددگار قانونی معاون ہیں جو {name} کے ساتھ WhatsApp پر بات کر رہے ہیں۔ "
                    f"آپ کا کام Ontario، کینیڈا کے قانونی سوالات کا جواب دینا ہے۔\n\n"
                    f"رہنما اصول:\n"
                    f"• دوستانہ، مختصر، اور مددگار رہیں - یہ WhatsApp ہے!\n"
                    f"• اردو میں جواب دیں کیونکہ صارف نے اردو میں پوچھا ہے\n"
                    f"• قانونی اصطلاحات اور کیس کے حوالے انگریزی میں رکھیں\n"
                    f"• اگر آپ کو علم نہیں، تو ایماندار رہیں اور قانونی مشورے کی تجویز دیں\n"
                    f"• گفتگو کو یاد رکھیں - فالو اپ سوالات پوچھیں\n\n"
                )
                if legal_context:
                    system_message += f"متعلقہ قانونی معلومات:\n{legal_context}\n\n"
                    system_message += "اس معلومات کی بنیاد پر، دوستانہ انداز میں جواب دیں۔"
                else:
                    system_message += "ابھی میرے پاس کوئی خاص قانونی معلومات نہیں ہے۔ عام رہنمائی فراہم کریں۔"
            else:
                system_message = (
                    f"You are a helpful legal assistant chatting with {name} on WhatsApp. "
                    f"You help answer questions about Ontario, Canada law.\n\n"
                    f"Guidelines:\n"
                    f"• Be friendly, concise, and helpful - this is WhatsApp!\n"
                    f"• Keep responses brief but informative (2-3 paragraphs max)\n"
                    f"• If you don't know based on the information available, be honest and suggest consulting a lawyer\n"
                    f"• Remember the conversation - ask follow-up questions\n"
                    f"• Use emojis occasionally to be personable 😊\n\n"
                )
                if legal_context:
                    system_message += f"Relevant legal information:\n{legal_context}\n\n"
                    system_message += "Based on this information, provide a conversational, friendly response."
                else:
                    system_message += "I don't have specific legal context right now. Provide general guidance."
            
            # Send system message (not stored in history)
            chat.send_message(system_message)
        else:
            logger.info(f"💬 Retrieving existing chat for {name} with wa_id {wa_id}")
            # Restore the chat session with existing history
            chat = conversation_model.start_chat(history=chat_history)
        
        # For follow-up messages in existing chats, enhance with new context if available
        if chat_history and LAWYAAR_AVAILABLE:
            legal_context = get_legal_context(message, wa_id, name)
            if legal_context:
                enhanced_message = f"{message}\n\n[New legal context available: {legal_context[:500]}...]"
                logger.info("📚 Enhanced follow-up with fresh legal context")
            else:
                enhanced_message = message
        else:
            enhanced_message = message
        
        # Send user's message and get response
        logger.info(f"👤 User ({detected_language}): {message[:100]}...")
        response = chat.send_message(enhanced_message)
        response_text = response.text
        
        # If input was in Urdu but response is in English, translate it
        if detected_language == 'ur' and not _is_urdu_text(response_text):
            logger.info("📝 Translating response to Urdu...")
            response_text = _translate_to_urdu(response_text)
        
        logger.info(f"🤖 Assistant: {response_text[:100]}...")
        
        # Update chat history (Gemini maintains it in chat.history)
        store_chat(wa_id, chat.history)
        
        return response_text
        
    except Exception as e:
        logger.error(f"❌ Error generating response: {e}", exc_info=True)
        # Detect language for error message
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
