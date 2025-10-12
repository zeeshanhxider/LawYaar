import logging
from flask import current_app, jsonify
import json
import requests
import os
import sys
import asyncio
import re
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from project root
env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Add LawYaar src to path
lawyaar_src = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
if lawyaar_src not in sys.path:
    sys.path.insert(0, lawyaar_src)

# Import LawYaar's legal service instead of Airbnb service
try:
    from whatsapp_legal_service import get_lawyaar_whatsapp_service
    USE_LAWYAAR = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Using LawYaar legal research system for WhatsApp responses")
except ImportError as e:
    USE_LAWYAAR = False
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️ LawYaar service not available, using fallback: {e}")

# Always import fallback service for error handling
try:
    from src.external.whatsappbot.app.services.llm_service import generate_response
except ImportError:
    # If gemini_service not available, create a simple fallback
    def generate_response(message, wa_id, name):
        return "I apologize, but the legal research system is currently unavailable. Please try again later."

from app.services.voice_handler import (
    download_audio_from_whatsapp,
    transcribe_audio,
    synthesize_speech,
    send_audio_reply,
    get_voice_handler,
)
from app.utils.message_tracker import get_message_tracker


def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")


def get_text_message_input(recipient, text, context_message_id=None):
    """Create a text message payload for WhatsApp API.
    
    Args:
        recipient (str): The WhatsApp ID of the recipient
        text (str): The message text to send
        context_message_id (str, optional): Message ID to reply to (creates threaded reply)
        
    Returns:
        str: JSON string with message payload
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    
    # Add context for reply threading if message_id provided
    if context_message_id:
        payload["context"] = {
            "message_id": context_message_id
        }
    
    return json.dumps(payload)


def send_message(data):
    """Send a JSON payload to the WhatsApp Cloud API.

    This function reads configuration from environment variables so it can be
    used both inside Flask and FastAPI contexts.
    """
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}",
    }

    version = os.getenv("VERSION")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"

    try:
        print(f"📤 Sending to WhatsApp API: {url}")
        print(f"📤 Payload: {data}")
        response = requests.post(url, data=data, headers=headers, timeout=10)
        print(f"📤 Response status: {response.status_code}")
        print(f"📤 Response body: {response.text}")
        response.raise_for_status()
    except requests.Timeout:
        logging.error("Timeout occurred while sending message")
        return None
    except requests.RequestException as e:
        logging.error(f"Request failed due to: {e}")
        print(f"❌ WhatsApp API Error: {e}")
        if hasattr(e, 'response') and getattr(e.response, 'text', None):
            print(f"❌ Error response body: {e.response.text}")
            logging.error(f"❌ Error response: {e.response.text}")
        return None
    else:
        log_http_response(response)
        return response


def mark_message_as_read(message_id):
    """Mark a WhatsApp message as read.
    
    Args:
        message_id (str): The ID of the WhatsApp message to mark as read
        
    Returns:
        response object or None: The API response if successful, None otherwise
    """
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}",
    }

    version = os.getenv("VERSION")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    })

    try:
        print(f"📖 Marking message as read: {message_id}")
        response = requests.post(url, data=payload, headers=headers, timeout=10)
        print(f"📖 Mark read status: {response.status_code}")
        response.raise_for_status()
        logging.info(f"✅ Message {message_id} marked as read")
        return response
    except requests.Timeout:
        logging.error(f"Timeout occurred while marking message {message_id} as read")
        return None
    except requests.RequestException as e:
        logging.error(f"Failed to mark message {message_id} as read: {e}")
        print(f"❌ Mark read API Error: {e}")
        if hasattr(e, 'response') and getattr(e.response, 'text', None):
            logging.error(f"❌ Error response: {e.response.text}")
        return None


def send_typing_indicator(recipient, action="typing"):
    """Send typing indicator or mark typing as stopped.
    
    Args:
        recipient (str): The WhatsApp ID of the recipient (with or without + prefix)
        action (str): Either "typing" to show typing indicator or "mark_as_read" to stop
        
    Returns:
        response object or None: The API response if successful, None otherwise
    """
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {os.getenv('ACCESS_TOKEN')}",
    }

    version = os.getenv("VERSION")
    phone_id = os.getenv("PHONE_NUMBER_ID")
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    
    # Remove '+' prefix if present for WhatsApp API
    recipient_clean = recipient.replace('+', '')
    
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_clean,
        action: True
    })

    try:
        print(f"⌨️ Sending '{action}' indicator to {recipient}")
        response = requests.post(url, data=payload, headers=headers, timeout=10)
        print(f"⌨️ Typing indicator status: {response.status_code}")
        response.raise_for_status()
        logging.info(f"✅ Typing indicator '{action}' sent to {recipient}")
        return response
    except requests.Timeout:
        logging.error(f"Timeout occurred while sending typing indicator to {recipient}")
        return None
    except requests.RequestException as e:
        logging.error(f"Failed to send typing indicator to {recipient}: {e}")
        print(f"❌ Typing indicator API Error: {e}")
        if hasattr(e, 'response') and getattr(e.response, 'text', None):
            logging.error(f"❌ Error response: {e.response.text}")
        return None


def send_document(recipient, document_path, caption=None, context_message_id=None):
    """Send a document file (PDF, DOC, etc.) via WhatsApp.
    
    Args:
        recipient (str): The WhatsApp ID of the recipient
        document_path (str): Local path to the document file
        caption (str, optional): Caption for the document
        context_message_id (str, optional): Message ID to reply to
        
    Returns:
        dict: Response from WhatsApp API, or None if send failed
    """
    try:
        access_token = os.getenv('ACCESS_TOKEN')
        phone_number_id = os.getenv('PHONE_NUMBER_ID')
        version = os.getenv('VERSION', 'v23.0')
        
        if not access_token or not phone_number_id:
            logger.error("❌ ACCESS_TOKEN or PHONE_NUMBER_ID not found")
            return None
        
        if not os.path.exists(document_path):
            logger.error(f"❌ Document file not found: {document_path}")
            return None
        
        logger.info(f"📤 Uploading and sending document to {recipient}")
        
        # Step 1: Upload document to WhatsApp
        upload_url = f"https://graph.facebook.com/{version}/{phone_number_id}/media"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        filename = os.path.basename(document_path)
        
        with open(document_path, 'rb') as doc_file:
            files = {
                'file': (filename, doc_file, 'application/pdf'),
                'messaging_product': (None, 'whatsapp'),
                'type': (None, 'application/pdf')
            }
            
            logger.info(f"⬆️ Uploading document: {filename}")
            upload_response = requests.post(
                upload_url,
                headers=headers,
                files=files,
                timeout=90  # PDFs can be large
            )
            upload_response.raise_for_status()
        
        upload_result = upload_response.json()
        media_id = upload_result.get('id')
        
        if not media_id:
            logger.error(f"❌ No media ID in upload response: {upload_result}")
            return None
        
        logger.info(f"✅ Document uploaded! Media ID: {media_id}")
        
        # Step 2: Send message with document
        message_url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
        
        # Remove '+' prefix for WhatsApp API
        recipient_clean = recipient.replace('+', '')
        
        message_data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_clean,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": filename
            }
        }
        
        # Add caption if provided
        if caption:
            message_data["document"]["caption"] = caption
        
        # Add context for reply threading
        if context_message_id:
            message_data["context"] = {
                "message_id": context_message_id
            }
        
        headers["Content-Type"] = "application/json"
        
        logger.info(f"📨 Sending document message...")
        send_response = requests.post(
            message_url,
            headers=headers,
            json=message_data,
            timeout=30
        )
        send_response.raise_for_status()
        
        result = send_response.json()
        logger.info(f"✅ Document sent successfully: {result}")
        
        return result
        
    except requests.Timeout:
        logger.error("⏱️ Timeout while sending document")
        return None
    except requests.RequestException as e:
        logger.error(f"❌ Failed to send document: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error sending document: {e}")
        return None


def process_text_for_whatsapp(text):
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text


def process_whatsapp_message(body):
    """
    Process incoming WhatsApp messages (text or voice).
    Responds with text for text messages, and voice for voice messages.
    """
    print("🔍 ENTERED process_whatsapp_message()")
    logging.info("🔍 ENTERED process_whatsapp_message()")
    
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    
    # Get message ID and check for duplicates
    message_id = message.get("id")
    tracker = get_message_tracker()
    
    if tracker.is_processed(message_id):
        print(f"⚠️ Message {message_id} already processed - skipping duplicate")
        logging.info(f"⚠️ Duplicate message detected: {message_id} - skipping")
        return
    
    # Mark this message as processed
    tracker.mark_processed(message_id)
    print(f"✅ Message {message_id} marked as processed")
    
    # Mark the message as read on WhatsApp
    mark_message_as_read(message_id)
    
    # Get message type
    message_type = message.get("type")
    # Send response back to the sender's WhatsApp number
    # wa_id comes without '+' prefix, so we need to add it
    recipient = f"+{wa_id}" if not wa_id.startswith('+') else wa_id
    
    # Show typing indicator
    send_typing_indicator(recipient, "typing")
    
    print(f"🔍 DEBUG: Message type = '{message_type}'")
    print(f"🔍 DEBUG: Recipient (sender) = '{recipient}'")
    logging.info(f"🔍 DEBUG: Message type = '{message_type}'")
    logging.info(f"🔍 DEBUG: Message keys = {list(message.keys())}")
    logging.info(f"🔍 DEBUG: Full message = {json.dumps(message, indent=2)}")
    
    if message_type == "audio":
        print(f"🎤 AUDIO DETECTED! Processing voice message from {name}")
        # Handle voice message
        logging.info(f"🎤 Voice message received from {name} ({wa_id})")
        
        try:
            print("📥 Step 1: Downloading audio from WhatsApp...")
            # 1. Download audio from WhatsApp
            media_id = message["audio"]["id"]
            print(f"📥 Media ID: {media_id}")
            audio_path = download_audio_from_whatsapp(media_id)
            print(f"📥 Audio downloaded to: {audio_path}")
            
            if not audio_path:
                print("❌ Failed to download audio!")
                logging.error("Failed to download audio")
                return
            
            print("✅ Download successful! Moving to transcription...")
            
            # 2. Transcribe audio to text
            print("🎤 Step 2: Transcribing audio with Gemini...")
            transcribed_text = transcribe_audio(audio_path)
            print(f"🎤 Transcription result: {transcribed_text}")
            
            if not transcribed_text:
                print("❌ Transcription failed or empty!")
                logging.error("Failed to transcribe audio")
                # Clean up downloaded file
                get_voice_handler().cleanup_temp_files(audio_path)
                return
            
            print(f"✅ Transcription successful: '{transcribed_text}'")
            logging.info(f"📝 Transcription from {name}: {transcribed_text}")
            
            # ✅ INTELLIGENT PDF STATE TRACKING
            # Only check for PDF rejection if there's actually a pending PDF offer
            from app.services.llm_service import check_if_chat_exists, _is_pdf_rejection, _handle_pdf_rejection
            
            # Check if there's a pending PDF offer in chat history
            has_pending_pdf_offer = False
            detected_language = 'en'  # default
            
            try:
                chat_history = check_if_chat_exists(wa_id)
                if chat_history and len(chat_history) > 0:
                    # Look for most recent message with research_data
                    for msg in reversed(chat_history):
                        if msg.get('role') == 'model' and 'research_data' in msg:
                            research_data = msg['research_data']
                            # Only consider it pending if type is "pending_pdf_request"
                            if research_data.get('type') == 'pending_pdf_request':
                                has_pending_pdf_offer = True
                                detected_language = research_data.get('detected_language', 'en')
                                logger.info("📋 Found pending PDF offer in chat history")
                            break
            except Exception as e:
                logger.warning(f"⚠️ Could not check PDF state: {e}")
            
            # ONLY check for rejection if there's an actual pending PDF offer
            if has_pending_pdf_offer and _is_pdf_rejection(transcribed_text):
                print("🚫 PDF rejection detected in VOICE (verified pending offer) - handling gracefully...")
                
                # Send friendly acknowledgment as VOICE reply
                rejection_response = _handle_pdf_rejection(wa_id, detected_language)
                
                # Synthesize rejection message to voice
                print("🗣️ Synthesizing rejection response to voice...")
                audio_path_tts = synthesize_speech(rejection_response, detected_language)
                
                if audio_path_tts:
                    # Send voice reply
                    print(f"📤 Sending voice rejection response to {recipient}...")
                    send_audio_reply(recipient, audio_path_tts, context_message_id=message_id)
                    get_voice_handler().cleanup_temp_files(audio_path_tts)
                else:
                    # Fallback to text if TTS fails
                    rejection_data = get_text_message_input(recipient, rejection_response, context_message_id=message_id)
                    send_message(rejection_data)
                
                # Cleanup audio
                get_voice_handler().cleanup_temp_files(audio_path)
                print("✅ PDF rejection handled via VOICE - conversation continues")
                return
            
            # 3. Generate AI response using Gemini + RAG
            print("🤖 Step 3: Generating AI response...")
            ai_response = generate_response(transcribed_text, wa_id, name, message_source='voice')  # ✅ VOICE queries get summary + PDF offer
            print(f"🤖 AI Response type: {type(ai_response)}")
            
            # Handle different response types
            if isinstance(ai_response, dict):
                response_type = ai_response.get('type', '')
                
                # Handle voice response with PDF prep (parallel PDF generation)
                if response_type == 'voice_with_pdf_prep':
                    print("📄 Voice response with PDF prep detected!")
                    voice_summary = ai_response.get('voice_summary', '')
                    research_data = ai_response.get('research_data', {})
                    detected_language = ai_response.get('detected_language', 'en')
                    
                    # Use the voice summary as the actual response
                    ai_response = voice_summary
                    
                    # Send voice response first
                    print(f"✅ Using voice summary ({len(voice_summary)} chars)")
                    print("🗣️ Synthesizing voice response...")
                    audio_path_tts = synthesize_speech(voice_summary, detected_language)
                    
                    if audio_path_tts:
                        print(f"📤 Sending voice response to {recipient}...")
                        send_audio_reply(recipient, audio_path_tts, context_message_id=message_id)
                        get_voice_handler().cleanup_temp_files(audio_path_tts)
                    else:
                        print("❌ TTS failed, sending text fallback")
                        text_data = get_text_message_input(recipient, voice_summary, context_message_id=message_id)
                        send_message(text_data)
                    
                    # Send PDF offer as TEXT message (after voice)
                    print("📄 Sending PDF offer message...")
                    if detected_language == 'ur':
                        pdf_offer = (
                            "📄 کیا آپ تفصیلی رپورٹ PDF میں چاہتے ہیں؟\n\n"
                            "✅ ہاں - PDF بھیجیں\n"
                            "❌ نہیں - شکریہ"
                        )
                    elif detected_language == 'sd':
                        pdf_offer = (
                            "📄 ڇا توهان تفصيلي رپورٽ PDF ۾ چاهيو ٿا؟\n\n"
                            "✅ ها - PDF موڪليو\n"
                            "❌ نه - مهرباني"
                        )
                    elif detected_language == 'bl':
                        pdf_offer = (
                            "📄 کیا آپ تفصیلی رپورٹ PDF میں چاہتے ہیں؟\n\n"
                            "✅ ہاں - PDF بھیجیں\n"
                            "❌ نہیں - شکریہ"
                        )
                    else:
                        pdf_offer = (
                            "📄 Would you like a detailed PDF report?\n\n"
                            "✅ Yes - Send PDF\n"
                            "❌ No - No thanks"
                        )
                    
                    offer_data = get_text_message_input(recipient, pdf_offer, context_message_id=message_id)
                    send_message(offer_data)
                    print("✅ PDF offer sent!")
                    
                    # TODO: Start background PDF generation here
                    # For now, PDF will be generated on-demand when user says "yes"
                    print("💡 PDF will be generated when user responds 'yes'")
                    
                    # Cleanup downloaded audio
                    get_voice_handler().cleanup_temp_files(audio_path)
                    return
                
                # Handle explicit PDF response
                elif response_type == 'pdf_response':
                    print("📄 PDF response detected!")
                    pdf_path = ai_response.get('pdf_path')
                    pdf_message = ai_response.get('message', 'Here is your detailed report.')
                    
                    # Send confirmation message first
                    print(f"📤 Sending PDF confirmation message...")
                    confirmation_data = get_text_message_input(recipient, pdf_message, context_message_id=message_id)
                    send_message(confirmation_data)
                    
                    # Send PDF document
                    if pdf_path and os.path.exists(pdf_path):
                        print(f"📤 Sending PDF document: {pdf_path}")
                        send_document(recipient, pdf_path, caption="LawYaar Legal Research Report", context_message_id=message_id)
                        
                        # Cleanup PDF file
                        try:
                            os.remove(pdf_path)
                            print(f"🗑️ Cleaned up PDF: {pdf_path}")
                        except:
                            pass
                    
                    # Cleanup downloaded audio
                    get_voice_handler().cleanup_temp_files(audio_path)
                    return
                
                # Unknown dict type - extract message if available
                else:
                    print(f"⚠️ Unknown response type: {response_type}")
                    ai_response = ai_response.get('message', str(ai_response))
            
            # At this point, ai_response should be a string
            if not isinstance(ai_response, str):
                print(f"❌ ERROR: ai_response is not a string: {type(ai_response)}")
                ai_response = str(ai_response)
            
            # Normal response - process as text
            ai_response = process_text_for_whatsapp(ai_response)
            
            logging.info(f"🤖 AI Response: {ai_response}")
            
            # 4. Convert response to speech (UpliftAI returns streaming URL)
            print("🗣️ Step 4: Synthesizing speech with UpliftAI...")
            audio_path_tts = synthesize_speech(ai_response, 'en')  # Text messages are in English
            print(f"�️ Audio file saved to: {audio_path_tts}")
            
            if not audio_path_tts:
                print("❌ Speech synthesis failed!")
                logging.error("Failed to generate speech")
                get_voice_handler().cleanup_temp_files(audio_path)
                return
            
            # 5. Send voice reply to recipient (upload file to WhatsApp)
            print(f"📤 Step 5: Uploading and sending voice reply to {recipient}...")
            result = send_audio_reply(recipient, audio_path_tts, context_message_id=message_id)
            print(f"📤 Send result: {result}")
            
            if result:
                logging.info(f"✅ Voice reply sent to {recipient}")
            else:
                logging.error("Failed to send voice reply")
            
            # Clean up downloaded audio files
            get_voice_handler().cleanup_temp_files(audio_path)
            get_voice_handler().cleanup_temp_files(audio_path_tts)
            
        except Exception as e:
            print(f"❌ EXCEPTION in voice handler: {e}")
            print(f"❌ Exception type: {type(e).__name__}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            logging.error(f"❌ Error processing voice message: {e}")
    
    elif message_type == "text":
        # Handle text message (existing logic)
        print("📝 TEXT MESSAGE DETECTED!")
        message_body = message["text"]["body"]
        print(f"📩 Text message from {name} ({wa_id}): {message_body}")
        logging.info(f"📩 Text message from {name} ({wa_id}): {message_body}")

        # ✅ INTELLIGENT PDF STATE TRACKING
        # Only check for PDF rejection if there's actually a pending PDF offer
        from app.services.llm_service import check_if_chat_exists, _is_pdf_rejection, _handle_pdf_rejection
        
        # Check if there's a pending PDF offer in chat history
        has_pending_pdf_offer = False
        detected_language = 'en'  # default
        
        try:
            chat_history = check_if_chat_exists(wa_id)
            if chat_history and len(chat_history) > 0:
                # Look for most recent message with research_data
                for msg in reversed(chat_history):
                    if msg.get('role') == 'model' and 'research_data' in msg:
                        research_data = msg['research_data']
                        # Only consider it pending if type is "pending_pdf_request"
                        if research_data.get('type') == 'pending_pdf_request':
                            has_pending_pdf_offer = True
                            detected_language = research_data.get('detected_language', 'en')
                            logger.info("📋 Found pending PDF offer in chat history")
                        break
        except Exception as e:
            logger.warning(f"⚠️ Could not check PDF state: {e}")
        
        # ONLY check for rejection if there's an actual pending PDF offer
        if has_pending_pdf_offer and _is_pdf_rejection(message_body):
            print("🚫 PDF rejection detected (verified pending offer) - handling gracefully...")
            
            # Send friendly acknowledgment
            rejection_response = _handle_pdf_rejection(wa_id, detected_language)
            rejection_data = get_text_message_input(recipient, rejection_response, context_message_id=message_id)
            send_message(rejection_data)
            print("✅ PDF rejection handled - conversation continues")
            return

        # Gemini Integration with RAG
        print("🤖 Generating AI response with Gemini + RAG...")
        response = generate_response(message_body, wa_id, name, message_source='text')  # ✅ TEXT queries now get summary + PDF offer (same as voice)
        
        # Handle different response types
        if isinstance(response, dict):
            response_type = response.get('type', '')
            
            # ✅ Handle text response with PDF prep (SAME AS VOICE)
            if response_type == 'text_with_pdf_prep':
                print("📄 Text response with PDF prep detected!")
                text_summary = response.get('text_summary', '')
                research_data = response.get('research_data', {})
                detected_language = response.get('detected_language', 'en')
                
                # Send text summary first
                print(f"✅ Using text summary ({len(text_summary)} chars)")
                print("📤 Sending text summary...")
                text_summary_formatted = process_text_for_whatsapp(text_summary)
                summary_data = get_text_message_input(recipient, text_summary_formatted, context_message_id=message_id)
                send_message(summary_data)
                
                # Send PDF offer as separate TEXT message (SAME AS VOICE)
                print("📄 Sending PDF offer message...")
                if detected_language == 'ur':
                    pdf_offer = (
                        "📄 کیا آپ تفصیلی رپورٹ PDF میں چاہتے ہیں؟\n\n"
                        "✅ ہاں - PDF بھیجیں\n"
                        "❌ نہیں - شکریہ"
                    )
                elif detected_language == 'sd':
                    pdf_offer = (
                        "📄 ڇا توهان تفصيلي رپورٽ PDF ۾ چاهيو ٿا؟\n\n"
                        "✅ ها - PDF موڪليو\n"
                        "❌ نه - مهرباني"
                    )
                elif detected_language == 'bl':
                    pdf_offer = (
                        "📄 کیا آپ تفصیلی رپورٹ PDF میں چاہتے ہیں؟\n\n"
                        "✅ ہاں - PDF بھیجیں\n"
                        "❌ نہیں - شکریہ"
                    )
                else:
                    pdf_offer = (
                        "📄 Would you like a detailed PDF report?\n\n"
                        "✅ Yes - Send PDF\n"
                        "❌ No - No thanks"
                    )
                
                offer_data = get_text_message_input(recipient, pdf_offer, context_message_id=message_id)
                send_message(offer_data)
                print("✅ PDF offer sent!")
                
                # PDF will be generated on-demand when user says "yes"
                print("💡 PDF will be generated when user responds 'yes'")
                return
            
            # Handle explicit PDF response (when user says "yes" to offer)
            elif response_type == 'pdf_response':
                print("📄 PDF response detected!")
                pdf_path = response.get('pdf_path')
                pdf_message = response.get('message', 'Here is your detailed report.')
                
                # Send confirmation message first
                print(f"📤 Sending PDF confirmation message...")
                confirmation_data = get_text_message_input(recipient, pdf_message, context_message_id=message_id)
                send_message(confirmation_data)
                
                # Send PDF document
                if pdf_path and os.path.exists(pdf_path):
                    print(f"📤 Sending PDF document: {pdf_path}")
                    send_document(recipient, pdf_path, caption="LawYaar Legal Research Report", context_message_id=message_id)
                    
                    # Cleanup PDF file
                    try:
                        os.remove(pdf_path)
                        print(f"🗑️ Cleaned up PDF: {pdf_path}")
                    except:
                        pass
                else:
                    print("⚠️ PDF path not found or doesn't exist")
                return
            
            # Unknown dict type - extract message if available
            else:
                print(f"⚠️ Unknown response type: {response_type}")
                response = str(response.get('voice_summary', '') or response.get('text_summary', '') or response.get('message', '') or 'Error processing response')
        
        # At this point, response should be a string
        if not isinstance(response, str):
            print(f"❌ ERROR: response is not a string: {type(response)}")
            response = str(response)
        
        # Normal text response
        print(f"🤖 AI Response generated ({len(response)} chars): {response[:100]}...")
        response = process_text_for_whatsapp(response)
        print(f"✅ Response formatted for WhatsApp")

        logging.info(f"📤 Sending text reply to {recipient}")
        print(f"📤 Sending text reply to {recipient}...")
        
        # Send text message to the sender as a reply (with context)
        data = get_text_message_input(recipient, response, context_message_id=message_id)
        result = send_message(data)
        print(f"📤 Send result: {result}")
    
    else:
        # Handle other message types
        logging.info(f"⚠️ Unsupported message type: {message_type} from {name} ({wa_id})")
        logging.info("Supported types: text, audio")


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )

