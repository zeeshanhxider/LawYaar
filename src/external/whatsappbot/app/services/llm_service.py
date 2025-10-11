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
- In {'Urdu' if detected_language == 'ur' else 'Sindhi' if detected_language == 'sd' else 'Balochi' if detected_language == 'bl' else 'English'}

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
- In {'Urdu' if detected_language == 'ur' else 'Sindhi' if detected_language == 'sd' else 'Balochi' if detected_language == 'bl' else 'English'}
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
                elif detected_language == 'sd':
                    pdf_message = f"📄 هتي {doc_count} لاڳاپيل ڪيسز سان گڏ تفصيلي PDF رپورٽ آهي."
                elif detected_language == 'bl':
                    pdf_message = f"📄 اتي {doc_count} متعلقہ کیسز کے ساتھ تفصیلی PDF رپورٹ ہے۔"
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
            elif detected_language == 'sd':
                pdf_offer = f"\n\nجيڪڏهن توهان سڀني ڪيسز جي تفصيلن ۽ لنڪس سان گڏ مڪمل تفصيلي رپورٽ چاهيو ٿا، ته مهرباني ڪري 'ها' يا 'جي' موڪليو. آئون توهان کي هڪ جامع PDF دستاويز موڪليندس."
            elif detected_language == 'bl':
                pdf_offer = f"\n\nاگر تہان سار کيساں دی تفصیلاں تے لنکس نال مل کر مکمل تفصیلی رپورٹ چاہتے ہو، تو برائے مہربانی 'ہاں' یا 'جی' بھیجو۔ میں تہان کو ایک جامع PDF دستاویز بھیجوں گا۔"
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
                "معذرت!  مجھے آپ کے سوال کا جواب دینے میں دشواری ہو رہی ہے۔\n\n"
                "براہ کرم:\n"
                "• اپنا سوال دوبارہ لکھیں\n"
                "• یا کچھ دیر بعد کوشش کریں\n\n"
                "شکریہ! "
            )
        elif detected_lang == 'sd':
            return (
                "معافي ڪجو!  مون توهان جي سوال جو جواب ڏيڻ ۾ تڪليف ٿي رهي آهي.\n\n"
                "مهرباني ڪري:\n"
                "• پنھنجو سوال ٻيهر لکو\n"
                "• يا ڪجھ دير بعد ڪوشش ڪريو\n\n"
                "مهرباني! "
            )
        elif detected_lang == 'bl':
            return (
                "معافی!  مجھے آپ کے سوال کا جواب دینے میں دشواری ہو رہی ہے۔\n\n"
                "برائے مہربانی:\n"
                "• اپنا سوال دوبارہ لکھیں\n"
                "• یا کچھ دیر بعد کوشش کریں\n\n"
                "شکریہ!"
            )
        return (
            "I apologize! I'm having trouble processing your question.\n\n"
            "Please try:\n"
            "• Rephrasing your question\n"
            "• Asking again in a few moments\n\n"
            "Thank you for your patience! 🙏"
        )


def _detect_language(text: str) -> str:
    """
    Detect if text is in Urdu, Sindhi, Balochi, or English using LLM for intelligent detection.

    Args:
        text: Input text to detect language

    Returns:
        str: 'ur' for Urdu, 'sd' for Sindhi, 'bl' for Balochi, 'en' for English
    """
    # Use LLM for intelligent detection
    try:
        from utils.call_llm import call_llm

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
- "کِرایِداراں کے کَے حُقُوق ءَنت؟"→ BALOCHI
- "Property dispute in Karachi" → ENGLISH (but context suggests Urdu response might be preferred)
- "میرا گھر چھین لیا گیا ہے" → URDU
- "مون کي گهر کسي چوري ڪري ورتو" → SINDHI
- "مور گَر چوری ڪَت گئی" → BALOCHI

Respond with ONLY ONE WORD: "ENGLISH", "URDU", "SINDHI", or "BALOCHI"

DETECTED LANGUAGE:"""

        result = call_llm(detection_prompt).strip().upper()

        # Map LLM response to our codes
        if "URDU" in result:
            return 'ur'
        elif "SINDHI" in result:
            return 'sd'
        elif "BALOCHI" in result:
            return 'bl'
        elif "ENGLISH" in result:
            return 'en'
        else:
            # Fallback to script-based detection
            logger.warning(f"LLM returned unclear result: {result}, falling back to script detection")
    except Exception as e:
        logger.error(f"LLM language detection failed: {e}, falling back to script detection")

    # Fallback: Count Urdu/Arabic script characters
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
    elif detected_language == 'sd':
        return (
            "ٺيڪ آهي، ڪا به ڳالهه ناهي! 😊\n\n"
            "جيڪڏهن توهان کي ڪو ٻيو قانوني سوال آهي ته آزادي سان پڇو. "
            "آئون هتي توهان جي مدد لاءِ آهيان! ⚖️"
        )
    elif detected_language == 'bl':
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
    Generate a comprehensive, professionally formatted PDF report with enhanced styling and detailed legal analysis.

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
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
        from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_RIGHT, TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.colors import HexColor, black, white, gray, blue, darkblue, lightgrey
        import tempfile
        from datetime import datetime

        # Register Urdu-compatible font using available system fonts
        urdu_font = 'Helvetica'  # Default fallback

        try:
            # Priority order: Arial Unicode MS (best) → Arial → Tahoma → Candara Arabic → Garamond
            font_options = [
                ('ArialUnicodeMS', r"C:\Windows\Fonts\ARIALUNI.ttf", "Arial Unicode MS"),
                ('Arial', r"C:\Windows\Fonts\arial.ttf", "Arial Regular"),
                ('Tahoma', r"C:\Windows\Fonts\tahoma.ttf", "Tahoma Regular"),
                ('Candarab', r"C:\Windows\Fonts\Candarab.ttf", "Candara Bold (Arabic)"),
                ('GaramondBold', r"C:\Windows\Fonts\GARABD.TTF", "Garamond Bold"),
            ]

            for font_name, font_path, display_name in font_options:
                if os.path.exists(font_path):
                    try:
                        pdfmetrics.registerFont(TTFont(font_name, font_path))
                        urdu_font = font_name
                        logger.info(f"✅ Registered {display_name} font for Urdu support")
                        break  # Use the first available font
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to register {display_name}: {e}")
                        continue

            if urdu_font == 'Helvetica':
                logger.warning("⚠️ No suitable system fonts found for Urdu, using Helvetica fallback")

        except Exception as font_error:
            logger.warning(f"⚠️ Font registration failed: {font_error}, using Helvetica fallback")
            urdu_font = 'Helvetica'

        # Extract research data with proper encoding handling
        query = research_data.get('query', 'Legal Query')
        full_legal_response = research_data.get('full_legal_response', '')
        pdf_links = research_data.get('pdf_links', [])
        doc_count = research_data.get('doc_count', 0)
        detected_language = research_data.get('detected_language', 'en')
        voice_summary = research_data.get('voice_summary', '')

        # Ensure all text data is properly encoded
        try:
            query = query.encode('utf-8', errors='replace').decode('utf-8')
            full_legal_response = full_legal_response.encode('utf-8', errors='replace').decode('utf-8')
            voice_summary = voice_summary.encode('utf-8', errors='replace').decode('utf-8')
        except Exception as encoding_error:
            logger.warning(f"Text encoding issue: {encoding_error}")
            # Continue with original text if encoding fails

        # Function to detect if text contains Urdu characters
        def is_urdu_text(text):
            if not text:
                return False
            urdu_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
            return urdu_chars / len(text) > 0.1  # More than 10% Urdu characters

        # Function to get appropriate style for text
        def get_text_style(text):
            if not text:
                return 'BodyText'
            urdu_ratio = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F') / len(text)
            if urdu_ratio > 0.5:  # More than 50% Urdu characters
                return 'UrduContent'  # Right-aligned for pure Urdu
            elif urdu_ratio > 0.1:  # Some Urdu characters
                return 'UrduText'    # Left-aligned for mixed content
            else:
                return 'BodyText'    # English text

        # Create PDF file
        temp_dir = tempfile.gettempdir()
        pdf_filename = f"LawYaar_Comprehensive_Report_{wa_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(temp_dir, pdf_filename)

        # Create PDF document with custom page templates
        doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                              rightMargin=50, leftMargin=50,
                              topMargin=80, bottomMargin=50)

        # Container for PDF elements
        story = []

        # Enhanced Styles with Professional Formatting
        styles = getSampleStyleSheet()

        # Title Style
        styles.add(ParagraphStyle(
            name='ReportTitle',
            parent=styles['Title'],
            fontName='Helvetica-Bold',
            fontSize=24,
            alignment=TA_CENTER,
            textColor=darkblue,
            spaceAfter=20,
            leading=28
        ))

        # Subtitle Style
        styles.add(ParagraphStyle(
            name='ReportSubtitle',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            alignment=TA_CENTER,
            textColor=blue,
            spaceAfter=15,
            leading=18
        ))

        # Section Header Style
        styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=16,
            alignment=TA_LEFT,
            textColor=darkblue,
            spaceBefore=15,
            spaceAfter=10,
            leading=20,
            borderColor=blue,
            borderWidth=0,
            borderPadding=5
        ))

        # Subsection Header Style
        styles.add(ParagraphStyle(
            name='SubsectionHeader',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            alignment=TA_LEFT,
            textColor=HexColor('#2E4057'),
            spaceBefore=10,
            spaceAfter=8,
            leading=18
        ))

        # Body Text Style with better font handling
        styles.add(ParagraphStyle(
            name='BodyText',
            parent=styles['Normal'],
            fontName=urdu_font,
            fontSize=11,
            alignment=TA_JUSTIFY,
            leading=14,
            spaceAfter=6,
            encoding='utf-8'  # Ensure UTF-8 encoding
        ))

        # Urdu-specific text style for better word formation
        styles.add(ParagraphStyle(
            name='UrduText',
            parent=styles['Normal'],
            fontName=urdu_font,
            fontSize=13,  # Slightly larger for better readability
            alignment=TA_LEFT,  # Left-aligned for mixed content, but can be changed to TA_RIGHT for pure Urdu
            leading=16,
            spaceAfter=8,
            encoding='utf-8',
            wordSpace=2,  # Better word spacing for Urdu
            allowWidows=0,  # Prevent single lines at page breaks
            allowOrphans=0,  # Prevent orphaned lines
        ))

        # Urdu title style
        styles.add(ParagraphStyle(
            name='UrduTitle',
            parent=styles['Heading2'],
            fontName=urdu_font,
            fontSize=16,
            alignment=TA_LEFT,
            textColor=darkblue,
            spaceAfter=10,
            leading=20,
            encoding='utf-8'
        ))

        # Pure Urdu content style (right-aligned)
        styles.add(ParagraphStyle(
            name='UrduContent',
            parent=styles['Normal'],
            fontName=urdu_font,
            fontSize=14,
            alignment=TA_RIGHT,  # Right-aligned for pure Urdu content
            leading=18,
            spaceAfter=8,
            encoding='utf-8',
            wordSpace=3,  # More spacing for Urdu words
        ))

        # Metadata Style
        styles.add(ParagraphStyle(
            name='Metadata',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            alignment=TA_LEFT,
            textColor=HexColor('#34495E'),
            leading=12
        ))

        # Footer Style
        styles.add(ParagraphStyle(
            name='Footer',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=9,
            alignment=TA_CENTER,
            textColor=gray,
            leading=11
        ))

        # Highlight Box Style
        styles.add(ParagraphStyle(
            name='HighlightBox',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=12,
            alignment=TA_LEFT,
            textColor=white,
            backColor=HexColor('#3498DB'),
            borderColor=HexColor('#2980B9'),
            borderWidth=1,
            borderPadding=8,
            leading=16
        ))

        # ================================
        # HEADER SECTION - Professional Branding (Localized)
        # ================================

        # Main Title with Enhanced Styling (Localized)
        if detected_language == 'ur':
            title_text = "🏛️ لاء یار قانونی تحقیق کی رپورٹ"
            subtitle_text = "سپریم کورٹ آف پاکستان کی کیس لاء کا جامع تجزیہ"
        elif detected_language == 'sd':
            title_text = "🏛️ لاء يار قانوني تحقيق جي رپورٽ"
            subtitle_text = "سپریم کورٽ آف پاڪستان جي ڪيس لاء جو جامع تجزيو"
        elif detected_language == 'bl':
            title_text = "🏛️ لاء یار قانونی تحقیق کی رپورٹ"
            subtitle_text = "سپریم کورٹ آف پاکستان کی کیس لاء کا جامع تجزیہ"
        else:
            title_text = "🏛️ LAWYAAR LEGAL RESEARCH REPORT"
            subtitle_text = "Comprehensive Supreme Court of Pakistan Case Law Analysis"

        title = Paragraph(title_text, styles['ReportTitle'])
        story.append(title)

        subtitle = Paragraph(subtitle_text, styles['ReportSubtitle'])
        story.append(subtitle)

        # Decorative line
        story.append(Spacer(1, 10))

        # ================================
        # METADATA SECTION - Enhanced Presentation (Localized)
        # ================================

        # Create metadata table for better organization
        current_time = datetime.now()

        if detected_language == 'ur':
            metadata_data = [
                ['📋 رپورٹ کی تفصیلات', ''],
                ['جناب کے لیے تیار کی گئی:', name],
                ['رپورٹ کی تاریخ:', current_time.strftime('%B %d, %Y')],
                ['رپورٹ کا وقت:', current_time.strftime('%I:%M %p')],
                ['کیسز کا تجزیہ:', f'{doc_count} متعلقہ کیسز'],
                ['زبان:', 'اردو/انگریزی'],
                ['رپورٹ آئی ڈی:', f'LY-{wa_id}-{current_time.strftime("%Y%m%d%H%M")}'],
            ]
        elif detected_language == 'sd':
            metadata_data = [
                ['📋 رپورٽ جي تفصيل', ''],
                ['جناب لاءِ تيار ڪيل:', name],
                ['رپورٽ جي تاريخ:', current_time.strftime('%B %d, %Y')],
                ['رپورٽ جو وقت:', current_time.strftime('%I:%M %p')],
                ['ڪيسز جو تجزيو:', f'{doc_count} لاڳاپيل ڪيس'],
                ['ٻولي:', 'سنڌي/انگريزي'],
                ['رپورٽ آءِ ڊي:', f'LY-{wa_id}-{current_time.strftime("%Y%m%d%H%M")}'],
            ]
        elif detected_language == 'bl':
            metadata_data = [
                ['📋 رپورٹ کی تفصیلات', ''],
                ['جناب کے لیے تیار کی گئی:', name],
                ['رپورٹ کی تاریخ:', current_time.strftime('%B %d, %Y')],
                ['رپورٹ کا وقت:', current_time.strftime('%I:%M %p')],
                ['کیسز کا تجزیہ:', f'{doc_count} متعلقہ کیسز'],
                ['زبان:', 'بلوچی/انگریزی'],
                ['رپورٹ آئی ڈی:', f'LY-{wa_id}-{current_time.strftime("%Y%m%d%H%M")}'],
            ]
        else:
            metadata_data = [
                ['📋 Report Details', ''],
                ['Generated for:', name],
                ['Report Date:', current_time.strftime('%B %d, %Y')],
                ['Report Time:', current_time.strftime('%I:%M %p')],
                ['Cases Analyzed:', f'{doc_count} relevant cases'],
                ['Language:', 'English'],
                ['Report ID:', f'LY-{wa_id}-{current_time.strftime("%Y%m%d%H%M")}'],
            ]

        # Create table with styling
        metadata_table = Table(metadata_data, colWidths=[2*inch, 4*inch])
        metadata_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#ECF0F1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), darkblue),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))

        story.append(metadata_table)
        story.append(Spacer(1, 20))

        # ================================
        # TABLE OF CONTENTS
        # ================================

        toc_title = Paragraph("<b>📖 TABLE OF CONTENTS</b>", styles['SectionHeader'])
        story.append(toc_title)
        story.append(Spacer(1, 10))

        toc_items = [
            "1. Executive Summary",
            "2. Your Legal Query",
            "3. Detailed Legal Analysis",
            "4. Key Findings & Principles",
            "5. Case References & Citations",
            "6. Additional Resources",
            "7. Methodology & Disclaimers"
        ]

        for item in toc_items:
            toc_item = Paragraph(item, styles['BodyText'])
            story.append(toc_item)
            story.append(Spacer(1, 3))

        story.append(Spacer(1, 15))

        # ================================
        # EXECUTIVE SUMMARY SECTION
        # ================================

        story.append(PageBreak())
        if detected_language == 'ur':
            exec_summary_title = Paragraph("<b>1. 📊 ایگزیکٹو سمری</b>", styles['SectionHeader'])
        elif detected_language == 'sd':
            exec_summary_title = Paragraph("<b>1. 📊 ايگزيڪيوٽو سميري</b>", styles['SectionHeader'])
        elif detected_language == 'bl':
            exec_summary_title = Paragraph("<b>1. 📊 ایگزیکٹو سمری</b>", styles['SectionHeader'])
        else:
            exec_summary_title = Paragraph("<b>1. 📊 EXECUTIVE SUMMARY</b>", styles['SectionHeader'])
        story.append(exec_summary_title)
        story.append(Spacer(1, 10))

        # Summary statistics in a highlighted box (Localized)
        if detected_language == 'ur':
            summary_stats = f"""
            <b>🔍 تحقیق کا جائزہ:</b><br/>
            • {doc_count} متعلقہ سپریم کورٹ کے کیسز کا تجزیہ کیا گیا<br/>
            • جامع قانونی تجزیہ فراہم کیا گیا<br/>
            • تمام حوالہ جات اور کیس لنکس شامل ہیں<br/>
            • پیشہ ورانہ قانونی تحقیق کی طریقہ کار کا اطلاق کیا گیا
            """
        elif detected_language == 'sd':
            summary_stats = f"""
            <b>🔍 تحقيق جو جائزو:</b><br/>
            • {doc_count} لاڳاپيل سپريم ڪورٽ جي ڪيسز جو تجزيو ڪيو ويو<br/>
            • جامع قانوني تجزيو مهيا ڪيو ويو<br/>
            • سڀ حوالا ۽ ڪيس لنڪ شامل آهن<br/>
            • پروفيشنل قانوني تحقيق جي طريقي جو اطلاق ڪيو ويو
            """
        elif detected_language == 'bl':
            summary_stats = f"""
            <b>🔍 تحقیق کا جائزہ:</b><br/>
            • {doc_count} متعلقہ سپریم کورٹ کے کیسز کا تجزیہ کیا گیا<br/>
            • جامع قانونی تجزیہ فراہم کیا گیا<br/>
            • تمام حوالہ جات اور کیس لنکس شامل ہیں<br/>
            • پیشہ ورانہ قانونی تحقیق کی طریقہ کار کا اطلاق کیا گیا
            """
        else:
            summary_stats = f"""
            <b>🔍 Research Overview:</b><br/>
            • Analyzed {doc_count} relevant Supreme Court cases<br/>
            • Comprehensive legal analysis provided<br/>
            • All citations and case links included<br/>
            • Professional legal research methodology applied
            """

        summary_box = Paragraph(summary_stats, styles['HighlightBox'])
        story.append(summary_box)
        story.append(Spacer(1, 15))

        # Voice summary content
        if voice_summary.strip():
            if detected_language == 'ur':
                summary_content = Paragraph("<b>💡 کلیدی نتائج:</b>", styles['SubsectionHeader'])
            elif detected_language == 'sd':
                summary_content = Paragraph("<b>💡 ڪليدي نتيجا:</b>", styles['SubsectionHeader'])
            elif detected_language == 'bl':
                summary_content = Paragraph("<b>💡 کلیدی نتائج:</b>", styles['SubsectionHeader'])
            else:
                summary_content = Paragraph("<b>💡 Key Findings:</b>", styles['SubsectionHeader'])
            story.append(summary_content)
            story.append(Spacer(1, 5))

            # Escape XML special characters in summary
            from xml.sax.saxutils import escape
            summary_escaped = escape(voice_summary)
            # Simple markdown conversion (bold only)
            import re
            summary_escaped = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', summary_escaped)
            summary_escaped = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', summary_escaped)

            style_name = get_text_style(voice_summary)
            story.append(Paragraph(summary_escaped, styles[style_name]))
            story.append(Spacer(1, 10))

        # ================================
        # USER QUERY SECTION (Localized)
        # ================================

        if detected_language == 'ur':
            query_title = Paragraph("<b>2. ❓ آپ کا قانونی سوال</b>", styles['SectionHeader'])
        elif detected_language == 'sd':
            query_title = Paragraph("<b>2. ❓ توهان جو قانوني سوال</b>", styles['SectionHeader'])
        elif detected_language == 'bl':
            query_title = Paragraph("<b>2. ❓ آپ کا قانونی سوال</b>", styles['SectionHeader'])
        else:
            query_title = Paragraph("<b>2. ❓ YOUR LEGAL QUERY</b>", styles['SectionHeader'])
        story.append(query_title)
        story.append(Spacer(1, 10))

        # Query in a bordered box (Localized)
        if detected_language == 'ur':
            query_label = "سوال:"
        elif detected_language == 'sd':
            query_label = "سوال:"
        elif detected_language == 'bl':
            query_label = "سوال:"
        else:
            query_label = "Query:"

        query_box_data = [[Paragraph(f"<b>{query_label}</b> {escape(query)}", styles['BodyText'])]]
        query_table = Table(query_box_data, colWidths=[7*inch])
        query_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#F8F9FA')),
            ('BOX', (0, 0), (-1, -1), 1, HexColor('#DEE2E6')),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))

        story.append(query_table)
        story.append(Spacer(1, 15))

        # ================================
        # DETAILED LEGAL ANALYSIS (Localized)
        # ================================

        story.append(PageBreak())
        if detected_language == 'ur':
            analysis_title = Paragraph("<b>3. ⚖️ تفصیلی قانونی تجزیہ</b>", styles['SectionHeader'])
        elif detected_language == 'sd':
            analysis_title = Paragraph("<b>3. ⚖️ تفصيلي قانوني تجزيو</b>", styles['SectionHeader'])
        elif detected_language == 'bl':
            analysis_title = Paragraph("<b>3. ⚖️ تفصیلی قانونی تجزیہ</b>", styles['SectionHeader'])
        else:
            analysis_title = Paragraph("<b>3. ⚖️ DETAILED LEGAL ANALYSIS</b>", styles['SectionHeader'])
        story.append(analysis_title)
        story.append(Spacer(1, 12))

        # Analysis introduction (Localized)
        if detected_language == 'ur':
            intro_text = """
            <b>جامع قانونی تحقیق اور تجزیہ</b><br/><br/>
            یہ سیکشن آپ کے قانونی سوال کا متعلقہ سپریم کورٹ آف پاکستان کی کیس لاء کی بنیاد پر گہرائی سے تجزیہ فراہم کرتا ہے۔
            تجزیہ متعدد کیسز سے معلومات کا امتزاج کرتا ہے، کلیدی قانونی اصولوں، فیصلوں اور عملی مضمرات کو اجاگر کرتا ہے۔
            """
        elif detected_language == 'sd':
            intro_text = """
            <b>جامع قانوني تحقيق ۽ تجزيو</b><br/><br/>
            هي سيڪشن توهان جي قانوني سوال جي لاڳاپيل سپريم ڪورٽ آف پاڪستان جي ڪيس لاء جي بنياد تي گهرائيءَ سان تجزيو مهيا ڪري ٿو.
            تجزيو گهڻن ڪيسز مان معلومات جو ميلاپ ڪري ٿو، ڪليدي قانوني اصولن، فيصلن ۽ عملي نتيجن کي اجاگر ڪري ٿو.
            """
        elif detected_language == 'bl':
            intro_text = """
            <b>جامع قانونی تحقیق اور تجزیہ</b><br/><br/>
            یہ سیکشن آپ کے قانونی سوال کا متعلقہ سپریم کورٹ آف پاکستان کی کیس لاء کی بنیاد پر گہرائی سے تجزیہ فراہم کرتا ہے۔
            تجزیہ متعدد کیسز سے معلومات کا امتزاج کرتا ہے، کلیدی قانونی اصولوں، فیصلوں اور عملی مضمرات کو اجاگر کرتا ہے۔
            """
        else:
            intro_text = """
            <b>Comprehensive Legal Research & Analysis</b><br/><br/>
            This section provides an in-depth analysis of your legal query based on relevant Supreme Court of Pakistan case law.
            The analysis synthesizes information from multiple cases, highlighting key legal principles, holdings, and practical implications.
            """
        story.append(Paragraph(intro_text, styles['BodyText']))
        story.append(Spacer(1, 10))

        # Main legal analysis content
        if full_legal_response.strip():
            try:
                # Escape and convert markdown to PDF-friendly format
                legal_text = escape(full_legal_response)

                # Enhanced markdown conversion
                legal_text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', legal_text)  # Bold
                legal_text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', legal_text)     # Italic
                legal_text = re.sub(r'^### (.*)$', r'<b>\1</b>', legal_text, flags=re.MULTILINE)  # H3 headers
                legal_text = re.sub(r'^## (.*)$', r'<b>\1</b>', legal_text, flags=re.MULTILINE)   # H2 headers
                legal_text = re.sub(r'^# (.*)$', r'<b>\1</b>', legal_text, flags=re.MULTILINE)    # H1 headers

                # Handle line breaks and paragraphs
                legal_text = legal_text.replace('\n\n', '<br/><br/>')
                legal_text = legal_text.replace('\n', '<br/>')

                # Ensure text is properly encoded for PDF
                legal_text = legal_text.encode('utf-8', errors='replace').decode('utf-8')

                # Split into paragraphs and add formatting
                paragraphs = legal_text.split('<br/><br/>')
                for i, para in enumerate(paragraphs):
                    para = para.strip()
                    if para and len(para) > 10:  # Filter out very short fragments
                        # Add paragraph numbering for main sections
                        if len(para) > 100:  # Substantial paragraphs
                            style_name = get_text_style(para)
                            story.append(Paragraph(f"<b>[{i+1}]</b> {para}", styles[style_name]))
                        else:
                            style_name = get_text_style(para)
                            story.append(Paragraph(para, styles[style_name]))
                        story.append(Spacer(1, 6))
            except Exception as text_error:
                logger.warning(f"Error processing legal text: {text_error}")
                # Fallback to simple text processing
                simple_text = escape(full_legal_response)
                style_name = get_text_style(simple_text)
                story.append(Paragraph(simple_text, styles[style_name]))
                story.append(Spacer(1, 6))

        # ================================
        # KEY FINDINGS SECTION
        # ================================

        story.append(PageBreak())
        findings_title = Paragraph("<b>4. 🎯 KEY FINDINGS & LEGAL PRINCIPLES</b>", styles['SectionHeader'])
        story.append(findings_title)
        story.append(Spacer(1, 10))

        # Extract key points from the analysis (simplified version)
        findings_text = """
        <b>📋 Summary of Key Legal Principles:</b><br/><br/>
        • <b>Precedent Analysis:</b> Relevant case law has been examined and applied to your specific query<br/>
        • <b>Legal Reasoning:</b> Analysis follows established judicial reasoning and legal methodology<br/>
        • <b>Practical Application:</b> Findings are directly applicable to real-world legal scenarios<br/>
        • <b>Case Citations:</b> All conclusions are supported by specific Supreme Court precedents
        """

        story.append(Paragraph(findings_text, styles['BodyText']))
        story.append(Spacer(1, 15))

        # ================================
        # CASE REFERENCES SECTION (Localized)
        # ================================

        story.append(PageBreak())
        if pdf_links and len(pdf_links) > 0:
            if detected_language == 'ur':
                references_title = Paragraph("<b>5. 📚 کیس حوالہ جات اور اقتباسات</b>", styles['SectionHeader'])
            elif detected_language == 'sd':
                references_title = Paragraph("<b>5. 📚 ڪيس حوالا ۽ اقتباس</b>", styles['SectionHeader'])
            elif detected_language == 'bl':
                references_title = Paragraph("<b>5. 📚 کیس حوالہ جات اور اقتباسات</b>", styles['SectionHeader'])
            else:
                references_title = Paragraph("<b>5. 📚 CASE REFERENCES & CITATIONS</b>", styles['SectionHeader'])
            story.append(references_title)
            story.append(Spacer(1, 12))

            if detected_language == 'ur':
                references_intro = f"""
                <b>کیس دستاویزات کا مکمل مجموعہ ({len(pdf_links)} کیسز)</b><br/><br/>
                ذیل میں اس رپورٹ میں تجزیہ کیے گئے تمام سپریم کورٹ کے کیسز کی جامع فہرست ہے۔
                ہر کیس میں اقتباس کی تفصیلات، کیس کے عنوانات اور سرکاری عدالت کے دستاویزات کے براہ راست لنکس شامل ہیں۔
                """
            elif detected_language == 'sd':
                references_intro = f"""
                <b>ڪيس دستاويز جو مڪمل ميلاپ ({len(pdf_links)} ڪيس)</b><br/><br/>
                هيٺ هن رپورٽ ۾ تجزيو ڪيل سڀني سپريم ڪورٽ جي ڪيسز جي جامع فهرست آهي.
                هر ڪيس ۾ اقتباس جي تفصيل، ڪيس جا عنوان ۽ سرڪاري عدالت جي دستاويز جي سڌي لنڪ شامل آهن.
                """
            elif detected_language == 'bl':
                references_intro = f"""
                <b>کیس دستاویزات کا مکمل مجموعہ ({len(pdf_links)} کیسز)</b><br/><br/>
                ذیل میں اس رپورٹ میں تجزیہ کیے گئے تمام سپریم کورٹ کے کیسز کی جامع فہرست ہے۔
                ہر کیس میں اقتباس کی تفصیلات، کیس کے عنوانات اور سرکاری عدالت کے دستاویزات کے براہ راست لنکس شامل ہیں۔
                """
            else:
                references_intro = f"""
                <b>Complete Case Documentation ({len(pdf_links)} cases)</b><br/><br/>
                Below is a comprehensive list of all Supreme Court cases analyzed in this report.
                Each case includes citation details, case titles, and direct links to official court documents.
                """
            story.append(Paragraph(references_intro, styles['BodyText']))
            story.append(Spacer(1, 10))

            # Create case reference cards (Localized labels)
            for i, pdf_info in enumerate(pdf_links, 1):
                case_no = pdf_info.get('case_no', 'Case')
                case_title = pdf_info.get('title', '')
                url = pdf_info.get('url', '')

                # Case card in a table format (Localized)
                if detected_language == 'ur':
                    case_data = [
                        [f'🏛️ کیس {i}: {case_no}', ''],
                        ['عنوان:', case_title if case_title else 'N/A'],
                        ['اقتباس:', case_no],
                        ['دستاویز لنک:', f'<a href="{url}">{url}</a>' if url else 'N/A'],
                    ]
                elif detected_language == 'sd':
                    case_data = [
                        [f'🏛️ ڪيس {i}: {case_no}', ''],
                        ['عنوان:', case_title if case_title else 'N/A'],
                        ['اقتباس:', case_no],
                        ['دستاويز لنڪ:', f'<a href="{url}">{url}</a>' if url else 'N/A'],
                    ]
                elif detected_language == 'bl':
                    case_data = [
                        [f'🏛️ کیس {i}: {case_no}', ''],
                        ['عنوان:', case_title if case_title else 'N/A'],
                        ['اقتباس:', case_no],
                        ['دستاویز لنک:', f'<a href="{url}">{url}</a>' if url else 'N/A'],
                    ]
                else:
                    case_data = [
                        [f'🏛️ Case {i}: {case_no}', ''],
                        ['Title:', case_title if case_title else 'N/A'],
                        ['Citation:', case_no],
                        ['Document Link:', f'<a href="{url}">{url}</a>' if url else 'N/A'],
                    ]

                case_table = Table(case_data, colWidths=[1.5*inch, 5.5*inch])
                case_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), HexColor('#3498DB')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), HexColor('#ECF0F1')),
                    ('TEXTCOLOR', (0, 1), (-1, -1), black),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 0.5, lightgrey),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))

                story.append(case_table)
                story.append(Spacer(1, 12))

        # ================================
        # ADDITIONAL RESOURCES SECTION (Localized)
        # ================================

        story.append(PageBreak())
        if detected_language == 'ur':
            resources_title = Paragraph("<b>6. 📖 اضافی وسائل</b>", styles['SectionHeader'])
        elif detected_language == 'sd':
            resources_title = Paragraph("<b>6. 📖 اضافي وسيلا</b>", styles['SectionHeader'])
        elif detected_language == 'bl':
            resources_title = Paragraph("<b>6. 📖 اضافی وسائل</b>", styles['SectionHeader'])
        else:
            resources_title = Paragraph("<b>6. 📖 ADDITIONAL RESOURCES</b>", styles['SectionHeader'])
        story.append(resources_title)
        story.append(Spacer(1, 12))

        if detected_language == 'ur':
            resources_text = """
            <b>🔗 مفید قانونی وسائل:</b><br/><br/>
            • <b>سپریم کورٹ آف پاکستان کی سرکاری ویب سائٹ:</b> www.supremecourt.gov.pk<br/>
            • <b>پاکستان قانونی معلومات کا مرکز:</b> www.paklii.org<br/>
            • <b>قانون اور انصاف کمیشن آف پاکستان:</b> www.ljcp.gov.pk<br/>
            • <b>قانونی تحقیق کے ڈیٹابیس:</b> پاکستان بار کونسل کے ذریعے دستیاب<br/><br/>
            <b>💼 پیشہ ورانہ قانونی خدمات:</b><br/>
            ذاتی نوعیت کی قانونی مشاورت اور نمائندگی کے لیے، اہل وکیلین اور قانونی پیشہ ورؤں سے رجوع کریں۔
            """
        elif detected_language == 'sd':
            resources_text = """
            <b>🔗 مفيد قانوني وسيلا:</b><br/><br/>
            • <b>سپريم ڪورٽ آف پاڪستان جي سرڪاري ويب سائيٽ:</b> www.supremecourt.gov.pk<br/>
            • <b>پاڪستان قانوني معلومات جو مرڪز:</b> www.paklii.org<br/>
            • <b>قانون ۽ انصاف ڪميشن آف پاڪستان:</b> www.ljcp.gov.pk<br/>
            • <b>قانوني تحقيق جا ڊيٽابيس:</b> پاڪستان بار ڪونسل جي ذريعي دستياب<br/><br/>
            <b>💼 پروفيشنل قانوني خدمتون:</b><br/>
            ذاتي نوعيت جي قانوني صلاح ۽ نمائندگي لاءِ، اهل وڪيلن ۽ قانوني پروفيشنلز سان رجوع ڪريو.
            """
        elif detected_language == 'bl':
            resources_text = """
            <b>🔗 مفید قانونی وسائل:</b><br/><br/>
            • <b>سپریم کورٹ آف پاکستان کی سرکاری ویب سائٹ:</b> www.supremecourt.gov.pk<br/>
            • <b>پاکستان قانونی معلومات کا مرکز:</b> www.paklii.org<br/>
            • <b>قانون اور انصاف کمیشن آف پاکستان:</b> www.ljcp.gov.pk<br/>
            • <b>قانونی تحقیق کے ڈیٹابیس:</b> پاکستان بار کونسل کے ذریعے دستیاب<br/><br/>
            <b>💼 پیشہ ورانہ قانونی خدمات:</b><br/>
            ذاتی نوعیت کی قانونی مشاورت اور نمائندگی کے لیے، اہل وکیلین اور قانونی پیشہ ورؤں سے رجوع کریں۔
            """
        else:
            resources_text = """
            <b>🔗 Useful Legal Resources:</b><br/><br/>
            • <b>Supreme Court of Pakistan Official Website:</b> www.supremecourt.gov.pk<br/>
            • <b>Pakistan Legal Information Center:</b> www.paklii.org<br/>
            • <b>Law & Justice Commission of Pakistan:</b> www.ljcp.gov.pk<br/>
            • <b>Legal Research Databases:</b> Available through Pakistan Bar Council<br/><br/>
            <b>💼 Professional Legal Services:</b><br/>
            For personalized legal advice and representation, consult qualified attorneys and legal professionals.
            """

        story.append(Paragraph(resources_text, styles['BodyText']))
        story.append(Spacer(1, 15))

        # ================================
        # METHODOLOGY & DISCLAIMERS (Localized)
        # ================================

        story.append(PageBreak())
        if detected_language == 'ur':
            methodology_title = Paragraph("<b>7. 🔬 طریقہ کار اور پیشہ ورانہ اخطاریے</b>", styles['SectionHeader'])
        elif detected_language == 'sd':
            methodology_title = Paragraph("<b>7. 🔬 طريقو ڪار ۽ پروفيشنل اختياريون</b>", styles['SectionHeader'])
        elif detected_language == 'bl':
            methodology_title = Paragraph("<b>7. 🔬 طریقہ کار اور پیشہ ورانہ اخطاریے</b>", styles['SectionHeader'])
        else:
            methodology_title = Paragraph("<b>7. 🔬 METHODOLOGY & PROFESSIONAL DISCLAIMERS</b>", styles['SectionHeader'])
        story.append(methodology_title)
        story.append(Spacer(1, 12))

        if detected_language == 'ur':
            methodology_text = """
            <b>🤖 AI کی طاقت سے چلنے والی قانونی تحقیق کی طریقہ کار:</b><br/><br/>
            یہ رپورٹ جدید AI ٹیکنالوجی کے ساتھ جامع قانونی ڈیٹابیس کا استعمال کرتے ہوئے تیار کی گئی ہے:<br/>
            • <b>ویکٹر ڈیٹابیس کی تلاش:</b> ایمبیڈنگز کا استعمال کرتے ہوئے کیس لاء کا سیمنٹک تجزیہ<br/>
            • <b>LLM تجزیہ:</b> بڑے لینگویج ماڈلز کا استعمال کرتے ہوئے قانونی اصولوں کا تجزیہ<br/>
            • <b>ماخذ کی تصدیق:</b> تمام حوالہ جات سرکاری عدالت کے دستاویزات سے منسلک ہیں<br/>
            • <b>کوالٹی کی یقین دہانی:</b> قانونی درستگی کی کثیر مرحلہ تصدیق<br/><br/>
            <b>⚠️ اہم پیشہ ورانہ اخطاریے:</b><br/><br/>
            • <i>یہ رپورٹ صرف معلوماتی مقاصد کے لیے ہے اور قانونی مشاورت نہیں ہے</i><br/>
            • <i>ہمیشہ اپنی صورت حال کے لیے اہل قانونی پیشہ ورؤں سے مشاورت کریں</i><br/>
            • <i>قوانین اور سابقے تبدیل ہو سکتے ہیں؛ ماہرین سے موجودہ حیثیت کی تصدیق کریں</i><br/>
            • <i>لاء یار تحقیق کی مدد فراہم کرتا ہے لیکن پیشہ ورانہ قانونی مشاورت کا متبادل نہیں ہے</i>
            """
        elif detected_language == 'sd':
            methodology_text = """
            <b>🤖 AI جي طاقت سان هلندڙ قانوني تحقيق جي طريقي ڪار:</b><br/><br/>
            هي رپورٽ جديد AI ٽيڪنالوجي سان جامع قانوني ڊيٽابيس جو استعمال ڪندي تيار ڪئي وئي آهي:<br/>
            • <b>ويڪٽر ڊيٽابيس جي ڳولا:</b> ايمبيڊنگ جو استعمال ڪندي ڪيس لاء جو سيمينٽڪ تجزيو<br/>
            • <b>LLM تجزيو:</b> وڏن ٻولي ماڊلز جو استعمال ڪندي قانوني اصولن جو تجزيو<br/>
            • <b>ماخذ جي تصديق:</b> سڀ حوالا سرڪاري عدالت جي دستاويز سان ڳنڍيل آهن<br/>
            • <b>ڪوالٽي جي يقيني ڪرڻ:</b> قانوني درستگي جي ڪيترن ئي مرحلن جي تصديق<br/><br/>
            <b>⚠️ اهم پروفيشنل اختياريون:</b><br/><br/>
            • <i>هي رپورٽ صرف معلوماتي مقصدن لاءِ آهي ۽ قانوني صلاح ناهي</i><br/>
            • <i>هميشه پنهن جي صورتحال لاءِ اهل قانوني پروفيشنلز سان صلاح ڪريو</i><br/>
            • <i>قانون ۽ سابقا تبديل ٿي سگهن ٿا؛ ماهرن سان موجوده حيثيت جي تصديق ڪريو</i><br/>
            • <i>لاء يار تحقيق جي مدد فراهم ڪري ٿو پر پروفيشنل قانوني صلاح جو متبادل ناهي</i>
            """
        elif detected_language == 'bl':
            methodology_text = """
            <b>🤖 AI کی طاقت سے چلنے والی قانونی تحقیق کی طریقہ کار:</b><br/><br/>
            یہ رپورٹ جدید AI ٹیکنالوجی کے ساتھ جامع قانونی ڈیٹابیس کا استعمال کرتے ہوئے تیار کی گئی ہے:<br/>
            • <b>ویکٹر ڈیٹابیس کی تلاش:</b> ایمبیڈنگز کا استعمال کرتے ہوئے کیس لاء کا سیمنٹک تجزیہ<br/>
            • <b>LLM تجزیہ:</b> بڑے لینگویج ماڈلز کا استعمال کرتے ہوئے قانونی اصولوں کا تجزیہ<br/>
            • <b>Source Verification:</b> تمام حوالہ جات سرکاری عدالت کے دستاویزات سے منسلک ہیں<br/>
            • <b>کوالٹی کی یقین دہانی:</b> قانونی درستگی کی کثیر مرحلہ تصدیق<br/><br/>
            <b>⚠️ اہم پیشہ ورانہ اخطاریے:</b><br/><br/>
            • <i>یہ رپورٹ صرف معلوماتی مقاصد کے لیے ہے اور قانونی مشاورت نہیں ہے</i><br/>
            • <i>ہمیشہ اپنی صورت حال کے لیے اہل قانونی پیشہ ورؤں سے مشاورت کریں</i><br/>
            • <i>قوانین اور سابقے تبدیل ہو سکتے ہیں؛ ماہرین سے موجودہ حیثیت کی تصدیق کریں</i><br/>
            • <i>لاء یار تحقیق کی مدد فراہم کرتا ہے لیکن پیشہ ورانہ قانونی مشاورت کا متبادل نہیں ہے</i>
            """
        else:
            methodology_text = """
            <b>🤖 AI-Powered Legal Research Methodology:</b><br/><br/>
            This report was generated using advanced AI technology combined with comprehensive legal databases:<br/>
            • <b>Vector Database Search:</b> Semantic analysis of case law using embeddings<br/>
            • <b>LLM Analysis:</b> Large language model synthesis of legal principles<br/>
            • <b>Source Verification:</b> All citations linked to official court documents<br/>
            • <b>Quality Assurance:</b> Multi-stage validation of legal accuracy<br/><br/>
            <b>⚠️ Important Professional Disclaimers:</b><br/><br/>
            • <i>This report is for informational purposes only and does not constitute legal advice</i><br/>
            • <i>Always consult qualified legal professionals for advice specific to your situation</i><br/>
            • <i>Laws and precedents may change; verify current status with legal experts</i><br/>
            • <i>LawYaar provides research assistance but is not a substitute for professional legal counsel</i>
            """

        story.append(Paragraph(methodology_text, styles['BodyText']))
        story.append(Spacer(1, 20))

        # ================================
        # FOOTER WITH CONTACT INFO (Localized)
        # ================================

        if detected_language == 'ur':
            footer_text = f"""
            <b>لاء یار - AI قانونی تحقیق کا معاون</b><br/>
            جدید AI ٹیکنالوجی سے چلتا ہے | سپریم کورٹ کی کیس لاء ڈیٹابیس<br/>
            تیار کی گئی: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br/>
            رپورٹ آئی ڈی: LY-{wa_id}-{datetime.now().strftime('%Y%m%d%H%M')}
            """
        elif detected_language == 'sd':
            footer_text = f"""
            <b>لاء يار - AI قانوني تحقيق جو مددگار</b><br/>
            جديد AI ٽيڪنالوجي سان هلندڙ | سپريم ڪورٽ جي ڪيس لاء ڊيٽابيس<br/>
            تيار ڪيل: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br/>
            رپورٽ آءِ ڊي: LY-{wa_id}-{datetime.now().strftime('%Y%m%d%H%M')}
            """
        elif detected_language == 'bl':
            footer_text = f"""
            <b>لاء یار - AI قانونی تحقیق کا معاون</b><br/>
            جدید AI ٹیکنالوجی سے چلتا ہے | سپریم کورٹ کی کیس لاء ڈیٹابیس<br/>
            تیار کی گئی: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br/>
            رپورٹ آئی ڈی: LY-{wa_id}-{datetime.now().strftime('%Y%m%d%H%M')}
            """
        else:
            footer_text = f"""
            <b>LawYaar - AI Legal Research Assistant</b><br/>
            Powered by Advanced AI Technology | Supreme Court Case Law Database<br/>
            Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br/>
            Report ID: LY-{wa_id}-{datetime.now().strftime('%Y%m%d%H%M')}
            """

        footer_table_data = [[
            Paragraph(footer_text, styles['Footer'])
        ]]

        footer_table = Table(footer_table_data, colWidths=[7*inch])
        footer_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#2C3E50')),
            ('TEXTCOLOR', (0, 0), (-1, -1), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(footer_table)

        # Build PDF with error handling
        try:
            doc.build(story)
            logger.info(f"✅ Enhanced PDF report generated successfully: {pdf_path}")
            return pdf_path
        except Exception as pdf_error:
            logger.error(f"❌ Error building PDF: {pdf_error}", exc_info=True)

            # Try fallback with basic fonts
            try:
                logger.info("🔄 Attempting PDF generation with fallback fonts...")

                # Reset story with basic fonts
                story_fallback = []

                # Use only basic fonts for fallback
                fallback_styles = getSampleStyleSheet()

                # Simple title
                title_fallback = Paragraph("LawYaar Legal Research Report", fallback_styles['Title'])
                story_fallback.append(title_fallback)
                story_fallback.append(Spacer(1, 12))

                # Basic metadata
                meta_fallback = f"Generated for: {name}\nDate: {datetime.now().strftime('%B %d, %Y')}\nCases Analyzed: {doc_count}"
                story_fallback.append(Paragraph(meta_fallback, fallback_styles['Normal']))
                story_fallback.append(Spacer(1, 12))

                # Basic content
                if full_legal_response.strip():
                    content_fallback = escape(full_legal_response)[:2000]  # Limit content length
                    story_fallback.append(Paragraph(content_fallback, fallback_styles['Normal']))

                # Build with fallback
                doc_fallback = SimpleDocTemplate(pdf_path, pagesize=A4,
                                               rightMargin=72, leftMargin=72,
                                               topMargin=72, bottomMargin=18)
                doc_fallback.build(story_fallback)

                logger.info(f"✅ PDF generated with fallback fonts: {pdf_path}")
                return pdf_path

            except Exception as fallback_error:
                logger.error(f"❌ Fallback PDF generation also failed: {fallback_error}")
                return None

    except Exception as e:
        logger.error(f"❌ Error generating enhanced PDF report: {e}", exc_info=True)
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
