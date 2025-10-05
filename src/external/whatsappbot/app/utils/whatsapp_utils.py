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
    from app.services.gemini_service import generate_response
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


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )


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
    
    # Get message type
    message_type = message.get("type")
    # Send response back to the sender's WhatsApp number
    # wa_id comes without '+' prefix, so we need to add it
    recipient = f"+{wa_id}" if not wa_id.startswith('+') else wa_id
    
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
            
            # 3. Generate AI response using Gemini + RAG
            print("🤖 Step 3: Generating AI response...")
            ai_response = generate_response(transcribed_text, wa_id, name)
            print(f"🤖 AI Response: {ai_response}")
            ai_response = process_text_for_whatsapp(ai_response)
            
            logging.info(f"🤖 AI Response: {ai_response}")
            
            # 4. Convert response to speech (UpliftAI returns streaming URL)
            print("🗣️ Step 4: Synthesizing speech with UpliftAI...")
            audio_path_tts = synthesize_speech(ai_response)
            print(f"�️ Audio file saved to: {audio_path_tts}")
            
            if not audio_path_tts:
                print("❌ Speech synthesis failed!")
                logging.error("Failed to generate speech")
                get_voice_handler().cleanup_temp_files(audio_path)
                return
            
            # 5. Send voice reply to recipient (upload file to WhatsApp)
            print(f"📤 Step 5: Uploading and sending voice reply to {recipient}...")
            result = send_audio_reply(recipient, audio_path_tts)
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

        # Gemini Integration with RAG
        print("🤖 Generating AI response with Gemini + RAG...")
        response = generate_response(message_body, wa_id, name)
        print(f"🤖 AI Response generated: {response}")
        response = process_text_for_whatsapp(response)
        print(f"✅ Response formatted for WhatsApp: {response}")

        logging.info(f"📤 Sending text reply to {recipient}: {response}")
        print(f"📤 Sending text reply to {recipient}...")
        
        # Send text message to the sender
        data = get_text_message_input(recipient, response)
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

