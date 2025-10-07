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
    
    # Quick keyword check for obvious greetings/chitchat (English + Urdu)
    chitchat_keywords = [
        # English greetings
        'hi', 'hello', 'hey', 'greetings', 'good morning', 'good afternoon', 'good evening',
        # Urdu/Arabic greetings
        'assalam', 'salam', 'السلام', 'وعليكم', 'ہیلو', 'ہائی',
        # Thanks/acknowledgments  
        'thanks', 'thank you', 'شکریہ', 'shukriya', 'jazakallah',
        # Simple responses
        'ok', 'okay', 'ٹھیک', 'اچھا', 'theek', 'acha',
        # Farewells
        'bye', 'goodbye', 'خدا حافظ', 'allah hafiz', 'khuda hafiz',
        # Questions about bot
        'how are you', 'what is your name', 'who are you', 'کون ہو', 'نام کیا'
    ]
    
    # If message is very short and matches chitchat, skip LLM call
    if len(message_lower) < 30 and any(keyword in message_lower for keyword in chitchat_keywords):
        logger.info(f"✅ Quick chitchat detection: {message[:30]}")
        return "CHITCHAT"
    
    # For ambiguous cases, use LLM to classify
    try:
        from utils.call_llm import call_llm
        
        classification_prompt = f"""You are a message classifier for a Pakistani legal assistant chatbot.

USER MESSAGE: "{message}"

TASK: Classify this message into ONE category:

A) CHITCHAT - Greetings, small talk, acknowledgments, questions about the bot
   Examples:
   - "Hi", "Hello", "Assalam o alaikum", "السلام عليكم"
   - "How are you?", "What's your name?", "Who are you?"
   - "Thanks", "Thank you", "شکریہ", "OK", "Okay", "ٹھیک ہے"
   - "Bye", "Goodbye", "خدا حافظ", "Allah hafiz"
   - Any greeting or social pleasantry

B) LEGAL - Questions about Pakistani law, legal rights, procedures, cases
   Examples:
   - "What are grounds for eviction?"
   - "Can I get bail in a murder case?"
   - "What are tenant rights in Pakistan?"
   - "How to file a petition?"
   - ANY question related to law, courts, legal rights, procedures
   
C) IRRELEVANT - Topics unrelated to law OR the bot
   Examples:
   - "What's the weather?", "Tell me a joke", "Recipe for biryani"
   - Math problems, sports scores, movie recommendations
   - General knowledge NOT related to law

IMPORTANT RULES:
1. If message is a greeting (hi, hello, salam, etc.) → CHITCHAT
2. If message asks about law/legal matters → LEGAL
3. Only use IRRELEVANT for topics completely outside law and greetings
4. When in doubt between CHITCHAT and LEGAL → choose CHITCHAT for greetings

Respond with ONLY one word: "CHITCHAT", "LEGAL", or "IRRELEVANT"

CLASSIFICATION:"""
        
        result = call_llm(classification_prompt).strip().upper()
        
        # Extract classification (prioritize CHITCHAT for greetings)
        if "CHITCHAT" in result:
            classification = "CHITCHAT"
        elif "LEGAL" in result:
            classification = "LEGAL"
        elif "IRRELEVANT" in result:
            classification = "IRRELEVANT"
        else:
            # Default to LEGAL to be safe
            classification = "LEGAL"
        
        logger.info(f"🤖 LLM classification: {classification} - Message: {message[:50]}")
        return classification
        
    except Exception as e:
        logger.error(f"Error classifying message: {e}")
        # Default to LEGAL to be safe (better to over-search than miss queries)
        return "LEGAL"


def _handle_chitchat(message: str, wa_id: str, name: str) -> str:
    """
    Generate a friendly conversational response for non-legal messages.
    Automatically detects language and responds accordingly.
    
    Args:
        message: The user's message
        wa_id: WhatsApp ID
        name: User's name
        
    Returns:
        str: Friendly conversational response in matching language
    """
    try:
        # Detect language of user's message
        detected_lang = _detect_language(message)
        logger.info(f"💬 Chitchat detected in {'Urdu' if detected_lang == 'ur' else 'English'}")
        
        # Get chat history for context
        chat_history = check_if_chat_exists(wa_id)
        
        from utils.call_llm import call_llm
        
        # Language-specific prompt
        if detected_lang == 'ur':
            chitchat_prompt = f"""You are a friendly Pakistani legal assistant chatbot on WhatsApp named "LawYaar".

USER: {name}
MESSAGE: {message}

Generate a warm, brief, conversational response IN URDU (2-3 sentences max). 

Guidelines:
- Respond in URDU script (اردو)
- Be friendly and professional
- If greeting, greet back and offer help with legal questions
- If thanks, acknowledge and offer further assistance
- Keep it SHORT (this is WhatsApp)
- Use emojis sparingly 😊

URDU RESPONSE:"""
        else:
            chitchat_prompt = f"""You are a friendly Pakistani legal assistant chatbot on WhatsApp named "LawYaar".

USER: {name}
MESSAGE: {message}

Generate a warm, brief, conversational response IN ENGLISH (2-3 sentences max). 

Guidelines:
- Respond in ENGLISH
- Be friendly and professional
- If greeting, greet back and offer help with legal questions
- If thanks, acknowledge and offer further assistance
- Keep it SHORT (this is WhatsApp)
- Use emojis sparingly 😊

ENGLISH RESPONSE:"""
        
        chitchat_response = call_llm(chitchat_prompt).strip()
        
        # Store in chat history
        new_history = chat_history if chat_history else []
        new_history.append({"role": "user", "parts": [message]})
        new_history.append({"role": "model", "parts": [chitchat_response]})
        store_chat(wa_id, new_history)
        
        logger.info(f"✅ Chitchat response generated for {name} in {'Urdu' if detected_lang == 'ur' else 'English'}")
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


def generate_response(message, wa_id, name, message_source='text'):
    """
    Generate a HYBRID response: Friendly summary + Full legal research + PDF links.
    
    Uses LawYaar's multi-agent legal research pipeline (same as CLI) but wraps it
    in a conversational, easy-to-understand format for WhatsApp users.
    
    Architecture:
    1. Check if message is a legal query (filter greetings/chitchat)
    2. Run full legal research pipeline (Classification → Retrieval → Pruning → Reading → Aggregation)
    3. For TEXT queries: Generate and send PDF immediately
    4. For VOICE queries: Send voice summary + PDF offer
    
    Args:
        message (str): The user's legal query
        wa_id (str): WhatsApp ID of the user
        name (str): Name of the user
        message_source (str): 'text' or 'voice' - determines response format
        
    Returns:
        For voice: dict with voice_summary and research_data
        For text: dict with pdf_path for immediate PDF sending
    """
    try:
        logger.info(f"🔍 Processing {'TEXT' if message_source == 'text' else 'VOICE'} query for {name}: {message[:100]}...")
        
        if not LAWYAAR_AVAILABLE:
            logger.error("❌ LawYaar legal research system not available")
            return ("I apologize, but the legal research system is currently unavailable. "
                   "Please try again later.")
        
        # ✨ INTELLIGENT ROUTING WITH PDF REQUEST PRIORITY
        
        # STEP 0: CHECK FOR PDF REQUEST FIRST (before classification)
        # This prevents "yes", "ok" from being classified as chitchat when user is responding to PDF offer
        chat_history = check_if_chat_exists(wa_id)
        if chat_history and len(chat_history) > 0:
            last_bot_message = None
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    last_bot_message = msg
                    break
            
            # Check if there's a PENDING PDF offer
            has_pending_pdf = (last_bot_message and 
                             last_bot_message.get('research_data', {}).get('type') == 'pending_pdf_request')
            
            # If pending PDF exists AND message is short (likely a response), check for affirmative FIRST
            message_word_count = len(message.split())
            is_short_response = message_word_count <= 5
            
            if has_pending_pdf and is_short_response and _is_pdf_request(message):
                logger.info(f"📄 PDF request detected BEFORE classification (short affirmative after legal query)")
                research_data = last_bot_message.get('research_data', {})
                
                # Get language before PDF generation
                detected_lang = research_data.get('detected_language', 'en')
                
                # Generate PDF
                pdf_path = generate_pdf_report(wa_id, name, research_data)
                
                # ✅ CLEAR PENDING PDF STATE - Mark as fulfilled
                try:
                    research_data['type'] = 'pdf_fulfilled'  # Change state
                    # Update chat history to mark PDF as sent
                    for msg in reversed(chat_history):
                        if msg.get('role') == 'model' and 'research_data' in msg:
                            msg['research_data']['type'] = 'pdf_fulfilled'
                            break
                    store_chat(wa_id, chat_history)
                    logger.info("✅ Marked PDF state as fulfilled")
                except Exception as e:
                    logger.warning(f"⚠️ Could not update PDF state: {e}")
                
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
        
        # STEP 1: Classify the message (LEGAL, CHITCHAT, or IRRELEVANT)
        message_type = _is_legal_query(message)
        logger.info(f"📊 Message classified as: {message_type}")
        
        # STEP 2: Handle NON-LEGAL messages immediately (don't check for PDF)
        # ✅ IMPORTANT: Non-legal messages also invalidate any pending PDF offers
        if message_type == "CHITCHAT":
            logger.info(f"💬 Chitchat detected: {message[:50]}... Responding conversationally")
            
            # Invalidate any pending PDF offer
            chat_history = check_if_chat_exists(wa_id)
            if chat_history and len(chat_history) > 0:
                try:
                    for msg in reversed(chat_history):
                        if msg.get('role') == 'model' and 'research_data' in msg:
                            if msg['research_data'].get('type') == 'pending_pdf_request':
                                msg['research_data']['type'] = 'pdf_expired'
                                logger.info("🔄 Invalidated pending PDF offer - user sent chitchat")
                            break
                    store_chat(wa_id, chat_history)
                except Exception as e:
                    logger.warning(f"⚠️ Could not invalidate PDF state: {e}")
            
            return _handle_chitchat(message, wa_id, name)
            
        elif message_type == "IRRELEVANT":
            logger.info(f"🚫 Irrelevant query detected: {message[:50]}... Politely declining")
            
            # Invalidate any pending PDF offer
            chat_history = check_if_chat_exists(wa_id)
            if chat_history and len(chat_history) > 0:
                try:
                    for msg in reversed(chat_history):
                        if msg.get('role') == 'model' and 'research_data' in msg:
                            if msg['research_data'].get('type') == 'pending_pdf_request':
                                msg['research_data']['type'] = 'pdf_expired'
                                logger.info("🔄 Invalidated pending PDF offer - user sent irrelevant query")
                            break
                    store_chat(wa_id, chat_history)
                except Exception as e:
                    logger.warning(f"⚠️ Could not invalidate PDF state: {e}")
            
            return _handle_irrelevant(message, wa_id, name)
        
        
        # STEP 4: Process as NEW LEGAL QUERY (message_type == "LEGAL")
        # ✅ IMPORTANT: Automatically invalidate any old pending PDF offers
        # User has moved on to a new query, so old offer is no longer relevant
        if chat_history and len(chat_history) > 0:
            try:
                for msg in reversed(chat_history):
                    if msg.get('role') == 'model' and 'research_data' in msg:
                        old_state = msg['research_data'].get('type')
                        if old_state == 'pending_pdf_request':
                            msg['research_data']['type'] = 'pdf_expired'  # Mark as expired
                            logger.info("🔄 Invalidated old pending PDF offer - user moved to new query")
                        break
                store_chat(wa_id, chat_history)
            except Exception as e:
                logger.warning(f"⚠️ Could not invalidate old PDF state: {e}")
        
        logger.info(f"⚖️ Processing new legal query: {message[:50]}...")
        
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
- NO bullet points, NO special formatting (this is for AUDIO, not text!)
- Keep it focused but comprehensive (400-500 words for voice)
- Use examples and analogies when helpful
- Structure as natural paragraphs with clear flow
- In {'Urdu' if detected_language == 'ur' else 'English'}

USER'S QUESTION: {message}

DETAILED LEGAL RESEARCH WITH ALL FINDINGS:
{full_legal_response}

IMPORTANT: Synthesize ALL the key legal information into a natural spoken explanation. Imagine you're explaining to someone who cannot read. Be thorough but natural. Remember: this will be converted to AUDIO, so write as you would SPEAK, not as you would WRITE.

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
        
        # ✅ DIFFERENT HANDLING FOR TEXT vs VOICE
        if message_source == 'text':
            # For TEXT queries: Send SUMMARY + PDF immediately
            logger.info(f"📄 TEXT query detected - generating executive summary + PDF")
            
            # Create EXECUTIVE SUMMARY (NO metadata - just legal findings)
            text_summary_prompt = f"""You are a professional legal assistant providing an executive summary to a literate user via WhatsApp.

YOUR TASK: Create a DENSE, EXECUTIVE SUMMARY that:
- DIRECTLY ANSWERS the user's legal question with the key findings
- Focuses ONLY on legal principles, rights, procedures, and outcomes
- Synthesizes findings from multiple cases into coherent principles
- NO case names, NO judge names, NO dates, NO citation numbers
- NO metadata - save all that for the detailed PDF
- Uses bullet points for clarity
- Professional but accessible language
- In {'Urdu' if detected_language == 'ur' else 'English'}
- Keep it concise and actionable (200-300 words)

USER'S QUESTION: {message}

DETAILED LEGAL RESEARCH WITH ALL FINDINGS:
{full_legal_response}

DOCUMENT COUNT: {doc_count} relevant cases analyzed

CRITICAL RULES:
- Extract ONLY the legal principles and findings
- DO NOT mention case names (e.g., "Ali v. Hassan") 
- DO NOT mention judges, courts, or dates
- DO NOT include citations or reference numbers
- Focus on WHAT the law says, not WHERE it comes from
- End with a brief note that detailed citations are in the attached PDF

EXECUTIVE SUMMARY:"""
            
            try:
                text_summary = call_llm(text_summary_prompt).strip()
                logger.info(f"✅ Generated executive summary: {len(text_summary)} chars")
            except Exception as e:
                logger.error(f"⚠️ LLM API error generating text summary: {e}")
                # Fallback: Use voice summary
                text_summary = voice_summary
            
            # Store research data for chat history
            research_context = {
                "type": "pdf_fulfilled",  # Mark as already fulfilled
                "query": message,
                "full_legal_response": full_legal_response,
                "pdf_links": pdf_links,
                "doc_count": doc_count,
                "detected_language": detected_language,
                "text_summary": text_summary
            }
            
            # Generate PDF immediately
            pdf_path = generate_pdf_report(wa_id, name, research_context)
            
            # Store in chat history
            try:
                chat_history = check_if_chat_exists(wa_id)
                if not chat_history:
                    chat_history = []
                
                chat_history.append({"role": "user", "parts": [message]})
                chat_history.append({
                    "role": "model", 
                    "parts": [text_summary],
                    "research_data": research_context
                })
                store_chat(wa_id, chat_history)
            except Exception as e:
                logger.error(f"Error storing chat history: {e}")
            
            # Return BOTH summary AND PDF
            if pdf_path:
                if detected_language == 'ur':
                    pdf_message = f"📄 یہاں {doc_count} متعلقہ کیسز کے ساتھ تفصیلی PDF رپورٹ ہے۔"
                    return {
                        "type": "text_with_pdf",
                        "text_summary": text_summary,
                        "pdf_path": pdf_path,
                        "pdf_message": pdf_message
                    }
                else:
                    pdf_message = f"📄 Here's the detailed PDF report with {doc_count} relevant cases."
                    return {
                        "type": "text_with_pdf",
                        "text_summary": text_summary,
                        "pdf_path": pdf_path,
                        "pdf_message": pdf_message
                    }
            else:
                # PDF generation failed - send text summary only
                logger.error("❌ PDF generation failed for text query - sending summary only")
                if detected_language == 'ur':
                    return text_summary + f"\n\n⚠️ معذرت! PDF بنانے میں خرابی ہوئی۔"
                else:
                    return text_summary + f"\n\n⚠️ Sorry! PDF generation failed."
        
        else:
            # For VOICE queries: Send voice summary + PDF OFFER (existing flow)
            logger.info(f"🎤 VOICE query detected - sending summary with PDF offer")
            
            # Add PDF offer at the end of voice summary
            if detected_language == 'ur':
                pdf_offer = f"\n\nاگر آپ مکمل تفصیلی رپورٹ چاہتے ہیں جس میں تمام کیسز کی تفصیلات اور لنکس ہوں، تو براہ کرم 'ہاں' یا 'جی' بھیجیں۔ میں آپ کو ایک تفصیلی PDF دستاویز بھیج دوں گا۔"
            else:
                pdf_offer = f"\n\nIf you'd like a detailed report with all case citations and links, please reply with 'yes' or 'haan'. I'll send you a comprehensive PDF document."
            
            voice_summary_with_offer = voice_summary + pdf_offer
            
            # Store research data for later PDF generation
            research_context = {
                "type": "pending_pdf_request",
                "query": message,
                "full_legal_response": full_legal_response,
                "pdf_links": pdf_links,
                "doc_count": doc_count,
                "detected_language": detected_language,
                "voice_summary": voice_summary
            }
            
            # Store in chat history
            try:
                chat_history = check_if_chat_exists(wa_id)
                if not chat_history:
                    chat_history = []
                
                chat_history.append({"role": "user", "parts": [message]})
                chat_history.append({
                    "role": "model", 
                    "parts": [voice_summary],
                    "research_data": research_context
                })
                store_chat(wa_id, chat_history)
            except Exception as e:
                logger.error(f"Error storing chat history: {e}")
            
            # Return voice response with PDF prep data
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
    Uses LLM for intelligent interpretation instead of keyword matching.
    
    Args:
        message: User's message
        
    Returns:
        bool: True if user wants PDF, False otherwise
    """
    message_lower = message.lower().strip()
    
    # If message is longer than 10 words, it's likely a new query, not a PDF request
    if len(message.split()) > 10:
        logger.info(f"📝 Message too long ({len(message.split())} words) - likely not a PDF request")
        return False
    
    # ✅ USE LLM FOR INTELLIGENT CLASSIFICATION (No hardcoded keywords!)
    try:
        from utils.call_llm import call_llm
        
        classification_prompt = f"""You are analyzing a user's response to a PDF offer in a WhatsApp conversation.

CONTEXT: The bot just offered to send a detailed PDF report and asked "Would you like a PDF report?"

USER'S RESPONSE: "{message}"

TASK: Classify this response as either:
- AFFIRMATIVE: User wants the PDF (says yes, agrees, requests it, etc.)
- NOT_AFFIRMATIVE: User is asking a new question, declining, or making any other statement (NOT requesting the PDF)

IMPORTANT RULES:
1. If user clearly agrees (like "yes", "haan", "sure", "send it", "please", "ji"), classify as AFFIRMATIVE
2. If user asks a NEW legal question (like "what about eviction?"), classify as NOT_AFFIRMATIVE
3. If user sends a greeting or irrelevant message (like "hi", "hello"), classify as NOT_AFFIRMATIVE
4. If user declines (like "no", "nahi", "later", "maybe later"), classify as NOT_AFFIRMATIVE
5. Consider cultural context: Urdu/English mixed responses
6. If unsure, classify as NOT_AFFIRMATIVE (safer to treat as new query)

EXAMPLES:
AFFIRMATIVE:
- "yes" → AFFIRMATIVE
- "haan" → AFFIRMATIVE
- "han" → AFFIRMATIVE
- "ji" → AFFIRMATIVE
- "sure" → AFFIRMATIVE
- "ok" → AFFIRMATIVE
- "send it" → AFFIRMATIVE
- "please send pdf" → AFFIRMATIVE
- "ہاں" → AFFIRMATIVE
- "جی" → AFFIRMATIVE
- "ضرور" → AFFIRMATIVE

NOT_AFFIRMATIVE:
- "what about property law?" → NOT_AFFIRMATIVE
- "can i evict a tenant?" → NOT_AFFIRMATIVE
- "no" → NOT_AFFIRMATIVE
- "nahi" → NOT_AFFIRMATIVE
- "نہیں" → NOT_AFFIRMATIVE
- "later" → NOT_AFFIRMATIVE
- "maybe later" → NOT_AFFIRMATIVE
- "hi" → NOT_AFFIRMATIVE
- "hello" → NOT_AFFIRMATIVE

Respond with ONLY one word: "AFFIRMATIVE" or "NOT_AFFIRMATIVE"

CLASSIFICATION:"""

        result = call_llm(classification_prompt).strip().upper()
        
        # Parse result
        is_affirmative = "AFFIRMATIVE" in result and "NOT_AFFIRMATIVE" not in result
        
        if is_affirmative:
            logger.info(f"🤖 LLM classified as AFFIRMATIVE: '{message[:50]}'")
        else:
            logger.info(f"✅ LLM classified as NOT_AFFIRMATIVE: '{message[:50]}'")
        
        return is_affirmative
        
    except Exception as e:
        logger.error(f"❌ Error in LLM classification for affirmative: {e}")
        
        # ⚠️ FALLBACK: Keyword matching (only if LLM fails!)
        logger.info("⚠️ Falling back to keyword-based affirmative detection")
        
        # Quick check for very obvious affirmatives
        obvious_yes = ['yes', 'yeah', 'yep', 'haan', 'han', 'ji', 'ہاں', 'جی']
        if message_lower in obvious_yes:
            logger.info(f"⚠️ Fallback quick match: '{message_lower}'")
            return True
        
        # English affirmatives
        english_yes = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'send', 'please']
        
        # Urdu affirmatives (romanized and script)
        urdu_yes = ['haan', 'haa', 'han', 'ji', 'jee', 'zaroor', 'ہاں', 'جی', 'ضرور']
        
        words = message_lower.split()
        
        # Check if any affirmative word appears
        for yes_word in english_yes + urdu_yes:
            if yes_word in words:
                logger.info(f"⚠️ Fallback keyword match: '{yes_word}'")
                return True
        
        # If message is very short (1-2 words) and not negative, assume yes
        if len(words) <= 2:
            negatives = ['no', 'nah', 'nope', 'nahi', 'نہیں']
            if not any(neg in words for neg in negatives):
                logger.info(f"⚠️ Fallback: Short message without negatives")
                return True
        
        return False


def _is_pdf_rejection(message: str) -> bool:
    """
    Check if user is rejecting/declining the PDF offer.
    Uses LLM for intelligent interpretation instead of keyword matching.
    
    Args:
        message: User's message
        
    Returns:
        bool: True if user doesn't want PDF, False otherwise
    """
    message_lower = message.lower().strip()
    
    # If message is longer than 10 words, it's likely a new query, not a rejection
    # This avoids unnecessary LLM calls for obvious legal queries
    if len(message.split()) > 10:
        logger.info(f"📝 Message too long ({len(message.split())} words) - likely not a rejection")
        return False
    
    # ✅ USE LLM FOR INTELLIGENT CLASSIFICATION (No hardcoded keywords!)
    try:
        from utils.call_llm import call_llm
        
        classification_prompt = f"""You are analyzing a user's response to a PDF offer in a WhatsApp conversation.

CONTEXT: The bot just offered to send a detailed PDF report and asked "Would you like a PDF report?"

USER'S RESPONSE: "{message}"

TASK: Classify this response as either:
- REJECTION: User clearly doesn't want the PDF (says no, declines, not interested, maybe later, skip, etc.)
- NOT_REJECTION: User is asking a new question, greeting, or making any other statement (NOT declining the PDF)

IMPORTANT RULES:
1. If user asks a NEW legal question (like "what about eviction?" or "can i evict a tenant?"), classify as NOT_REJECTION
2. If user sends a greeting (like "hi", "hello", "thanks", "thank you"), classify as NOT_REJECTION  
3. If user clearly declines (like "no", "nahi", "not now", "maybe later", "skip it"), classify as REJECTION
4. Consider cultural context: Urdu/English mixed responses
5. If unsure, classify as NOT_REJECTION (safer to process as new query than miss it)

EXAMPLES:
REJECTION:
- "no" → REJECTION
- "nah" → REJECTION
- "nope" → REJECTION
- "nahi" → REJECTION
- "نہیں" → REJECTION
- "not now" → REJECTION
- "maybe later" → REJECTION
- "not interested" → REJECTION
- "skip it" → REJECTION
- "pass" → REJECTION

NOT_REJECTION:
- "what about property law?" → NOT_REJECTION
- "can i evict a tenant?" → NOT_REJECTION
- "on what grounds can i evict?" → NOT_REJECTION
- "hi" → NOT_REJECTION
- "hello" → NOT_REJECTION
- "thanks" → NOT_REJECTION
- "thank you" → NOT_REJECTION

Respond with ONLY one word: "REJECTION" or "NOT_REJECTION"

CLASSIFICATION:"""

        result = call_llm(classification_prompt).strip().upper()
        
        # Parse result
        is_rejection = "REJECTION" in result and "NOT_REJECTION" not in result
        
        if is_rejection:
            logger.info(f"🤖 LLM classified as REJECTION: '{message[:50]}'")
        else:
            logger.info(f"✅ LLM classified as NOT_REJECTION: '{message[:50]}'")
        
        return is_rejection
        
    except Exception as e:
        logger.error(f"❌ Error in LLM classification for rejection: {e}")
        
        # ⚠️ FALLBACK: Word boundary matching (only if LLM fails!)
        logger.info("⚠️ Falling back to keyword-based rejection detection")
        
        # Quick check for very obvious rejections
        obvious_no = ['no', 'nah', 'nope', 'nahi', 'نہیں']
        if message_lower in obvious_no:
            logger.info(f"⚠️ Fallback quick match: '{message_lower}'")
            return True
        
        # English negatives
        english_no = ['no', 'nah', 'nope', 'not', 'dont', "don't", 'never', 'nvm', 
                      'skip', 'pass', 'later']
        
        # Urdu negatives (romanized and script)
        urdu_no = ['nahi', 'nhi', 'na', 'نہیں', 'نہ']
        
        words = message_lower.split()
        
        # Check if any negative word appears as a COMPLETE WORD
        for neg_word in english_no + urdu_no:
            if neg_word in words:
                logger.info(f"⚠️ Fallback keyword match: '{neg_word}'")
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
    # ✅ CLEAR PENDING PDF STATE - Mark as declined
    try:
        chat_history = check_if_chat_exists(wa_id)
        if chat_history and len(chat_history) > 0:
            # Find and update the last message with pending PDF
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    # Change state from pending to declined
                    msg['research_data']['type'] = 'pdf_declined'
                    break
            store_chat(wa_id, chat_history)
            logger.info("✅ Marked PDF state as declined")
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
