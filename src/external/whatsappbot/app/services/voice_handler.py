"""
Voice Message Handler for WhatsApp Bot
Handles voice message downloads, transcription, TTS synthesis, and sending audio replies.
"""

import logging
import os
import requests
import json
from pathlib import Path
import tempfile
from dotenv import load_dotenv

# Load environment variables from project root
# Find the .env file in the LawYaar project root (5 levels up from this file)
env_path = Path(__file__).parent.parent.parent.parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
logger_pre = logging.getLogger(__name__)
logger_pre.info(f"🔍 Loading .env from: {env_path} (exists: {env_path.exists()})")

# Configure logging
logger = logging.getLogger(__name__)


class VoiceMessageHandler:
    """Handles all voice message operations for the WhatsApp bot."""
    
    def __init__(self):
        self.temp_dir = Path(tempfile.gettempdir()) / "whatsapp_voice"
        self.temp_dir.mkdir(exist_ok=True)
        logger.info(f"Voice handler initialized. Temp directory: {self.temp_dir}")
    
    def download_audio_from_whatsapp(self, media_id):
        """
        Download audio file from WhatsApp using the media ID.
        
        Args:
            media_id (str): The WhatsApp media ID from the webhook message
            
        Returns:
            str: Path to the downloaded audio file, or None if download failed
        """
        try:
            access_token = os.getenv('ACCESS_TOKEN')
            version = os.getenv('VERSION', 'v23.0')
            
            if not access_token:
                logger.error("❌ ACCESS_TOKEN not found in environment variables")
                return None
            
            # Debug: Log token info (first/last 10 chars for security)
            token_preview = f"{access_token[:10]}...{access_token[-10:]}" if len(access_token) > 20 else "***"
            logger.info(f"🔑 Using ACCESS_TOKEN: {token_preview}")
            
            # Step 1: Get media URL from WhatsApp
            media_url = f"https://graph.facebook.com/{version}/{media_id}"
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            logger.info(f"🔍 Fetching media URL for media_id: {media_id}")
            response = requests.get(media_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            media_data = response.json()
            download_url = media_data.get('url')
            mime_type = media_data.get('mime_type', 'audio/ogg')
            
            if not download_url:
                logger.error("No download URL in media response")
                return None
            
            # Step 2: Download the actual audio file
            logger.info(f"⬇️ Downloading audio from: {download_url}")
            audio_response = requests.get(download_url, headers=headers, timeout=30)
            audio_response.raise_for_status()
            
            # Step 3: Save to temporary file
            file_extension = self._get_extension_from_mime(mime_type)
            file_path = self.temp_dir / f"voice_{media_id}{file_extension}"
            
            with open(file_path, 'wb') as f:
                f.write(audio_response.content)
            
            logger.info(f"✅ Audio downloaded successfully: {file_path} ({len(audio_response.content)} bytes)")
            return str(file_path)
            
        except requests.Timeout:
            logger.error("⏱️ Timeout while downloading audio from WhatsApp")
            return None
        except requests.RequestException as e:
            logger.error(f"❌ Failed to download audio: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error downloading audio: {e}")
            return None
    
    def transcribe_audio(self, file_path):
        """
        Transcribe audio file to text.
        
        Supports: upliftai (recommended), gemini, or google.
        Configure which service to use via TRANSCRIPTION_SERVICE env variable.
        
        Args:
            file_path (str): Path to the audio file to transcribe
            
        Returns:
            str: Transcribed text, or None if transcription failed
        """
        try:
            transcription_service = os.getenv('TRANSCRIPTION_SERVICE', 'upliftai').lower()
            
            if transcription_service == 'upliftai':
                return self._transcribe_with_upliftai(file_path)
            elif transcription_service == 'google':
                return self._transcribe_with_google_speech(file_path)
            elif transcription_service == 'gemini':
                return self._transcribe_with_gemini(file_path)
            else:
                logger.error(f"Unknown transcription service: {transcription_service}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")
            return None
    
    def _transcribe_with_upliftai(self, file_path):
        """
        Transcribe audio using UpliftAI Speech-to-Text API.
        
        Args:
            file_path (str): Path to the audio file
            
        Returns:
            str: Transcribed text
        """
        try:
            upliftai_api_key = os.getenv('UPLIFTAI_API_KEY')
            if not upliftai_api_key:
                logger.error("UPLIFTAI_API_KEY not found in environment variables")
                return None
            
            logger.info(f"🎤 Transcribing audio with UpliftAI: {file_path}")
            
            # UpliftAI Speech-to-Text API endpoint
            url = 'https://api.upliftai.org/v1/speech/transcribe'
            
            headers = {
                "Authorization": f"Bearer {upliftai_api_key}"
            }
            
            # Read audio file
            with open(file_path, 'rb') as audio_file:
                files = {
                    'file': audio_file
                }
                
                # Optional parameters
                data = {
                    'language': os.getenv('UPLIFTAI_TRANSCRIPTION_LANGUAGE', 'auto'),  # auto-detect or ur-PK, en-US
                    'model': os.getenv('UPLIFTAI_TRANSCRIPTION_MODEL', 'whisper-large-v3')
                }
                
                response = requests.post(
                    url,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60
                )
                response.raise_for_status()
            
            # Parse response
            result = response.json()
            transcription = result.get('text', '').strip()
            
            if not transcription:
                logger.error(f"No transcription in UpliftAI response: {result}")
                return None
            
            logger.info(f"✅ Transcription successful: {transcription[:100]}...")
            return transcription
            
        except requests.Timeout:
            logger.error("⏱️ Timeout while calling UpliftAI transcription API")
            return None
        except requests.RequestException as e:
            logger.error(f"❌ UpliftAI transcription error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error during UpliftAI transcription: {e}")
            return None
    
    def _transcribe_with_gemini(self, file_path):
        """
        Transcribe audio using Google Gemini API.
        
        Args:
            file_path (str): Path to the audio file
            
        Returns:
            str: Transcribed text
        """
        try:
            import google.generativeai as genai
            
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if not gemini_api_key:
                logger.error("GEMINI_API_KEY not found in environment variables")
                return None
            
            genai.configure(api_key=gemini_api_key)
            
            # Upload the audio file
            logger.info(f"🎤 Transcribing audio with Gemini: {file_path}")
            
            # Upload file to Gemini File API
            logger.info("⬆️ Uploading audio file to Gemini...")
            uploaded_file = genai.upload_file(file_path)
            logger.info(f"✅ File uploaded: {uploaded_file.name}")
            
            # Use gemini-2.5-flash (stable model that supports audio)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # Generate transcription
            logger.info("📝 Generating transcription...")
            response = model.generate_content([
                "Transcribe this audio message accurately. Only return the transcribed text, nothing else. If the audio is in Urdu or Arabic, transcribe it in the original language.",
                uploaded_file
            ])
            
            transcription = response.text.strip()
            logger.info(f"✅ Transcription successful: {transcription[:100]}...")
            
            # Clean up uploaded file
            try:
                uploaded_file.delete()
                logger.info("🗑️ Cleaned up uploaded file from Gemini")
            except:
                pass
            
            return transcription
            
        except Exception as e:
            logger.error(f"❌ Gemini transcription error: {e}")
            return None
    
    def _transcribe_with_google_speech(self, file_path):
        """
        Transcribe audio using Google Cloud Speech-to-Text API.
        
        Args:
            file_path (str): Path to the audio file
            
        Returns:
            str: Transcribed text
        """
        try:
            from google.cloud import speech
            
            logger.info(f"🎤 Transcribing audio with Google Speech-to-Text: {file_path}")
            
            client = speech.SpeechClient()
            
            with open(file_path, 'rb') as audio_file:
                content = audio_file.read()
            
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
                sample_rate_hertz=16000,
                language_code="en-US",
                alternative_language_codes=["ur-PK", "ar-SA"],  # Add support for Urdu and Arabic
                enable_automatic_punctuation=True,
            )
            
            response = client.recognize(config=config, audio=audio)
            
            transcription = ""
            for result in response.results:
                transcription += result.alternatives[0].transcript + " "
            
            transcription = transcription.strip()
            logger.info(f"✅ Transcription successful: {transcription[:100]}...")
            
            return transcription
            
        except Exception as e:
            logger.error(f"❌ Google Speech transcription error: {e}")
            return None
    
    def synthesize_speech(self, text):
        """
        Convert text to speech using UpliftAI TTS API.
        Returns the streaming URL that can be sent directly to WhatsApp.
        
        Args:
            text (str): Text to convert to speech
            
        Returns:
            str: UpliftAI streaming URL for the audio, or None if synthesis failed
        """
        try:
            upliftai_api_key = os.getenv('UPLIFTAI_API_KEY')
            upliftai_voice_id = os.getenv('UPLIFTAI_VOICE_ID', 'v_8eelc901')
            upliftai_output_format = os.getenv('UPLIFTAI_OUTPUT_FORMAT', 'MP3_22050_64')
            
            if not upliftai_api_key:
                logger.error("UPLIFTAI_API_KEY not found in environment variables")
                return None
            
            # Limit text length for TTS (very long texts can timeout)
            max_chars = 2000
            if len(text) > max_chars:
                logger.warning(f"⚠️ Text too long ({len(text)} chars), truncating to {max_chars}")
                text = text[:max_chars] + "..."
            
            logger.info(f"🗣️ Synthesizing speech with UpliftAI: {text[:100]}...")
            
            # UpliftAI TTS API request (async endpoint)
            url = 'https://api.upliftai.org/v1/synthesis/text-to-speech-async'
            headers = {
                "Authorization": f"Bearer {upliftai_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "voiceId": upliftai_voice_id,
                "text": text,
                "outputFormat": upliftai_output_format  # MP3_22050_64 - Optimized for WhatsApp
            }
            
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=60  # Increased timeout for TTS generation
            )
            response.raise_for_status()
            
            # Get mediaId and token from response
            response_data = response.json()
            media_id = response_data.get('mediaId')
            token = response_data.get('token')
            
            if not media_id or not token:
                logger.error(f"Missing mediaId or token in UpliftAI response: {response_data}")
                return None
            
            # Construct streaming URL
            audio_url = f"https://api.upliftai.org/v1/synthesis/stream-audio/{media_id}?token={token}"
            
            logger.info(f"✅ Speech synthesis successful. Downloading audio...")
            
            # Download the audio file immediately (tokens expire quickly)
            # Retry up to 3 times with increasing timeout
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    timeout = 60 + (attempt * 30)  # 60s, 90s, 120s
                    logger.info(f"🔄 Download attempt {attempt + 1}/{max_retries} (timeout: {timeout}s)")
                    
                    audio_response = requests.get(audio_url, timeout=timeout)
                    audio_response.raise_for_status()
                    
                    # Save to temp file
                    audio_filename = f"tts_{media_id}.mp3"
                    audio_path = self.temp_dir / audio_filename
                    
                    with open(audio_path, 'wb') as f:
                        f.write(audio_response.content)
                    
                    logger.info(f"✅ Audio downloaded to: {audio_path} ({len(audio_response.content)} bytes)")
                    return str(audio_path)  # Return file path instead of URL
                    
                except requests.Timeout:
                    if attempt < max_retries - 1:
                        logger.warning(f"⏱️ Timeout on attempt {attempt + 1}, retrying...")
                        continue
                    else:
                        logger.error(f"⏱️ All {max_retries} download attempts timed out")
                        return None
            
        except requests.Timeout:
            logger.error("⏱️ Timeout while calling UpliftAI TTS API")
            return None
        except requests.RequestException as e:
            logger.error(f"❌ UpliftAI API error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error during speech synthesis: {e}")
            return None
    
    def send_audio_reply(self, to, audio_path, context_message_id=None):
        """
        Send audio message via WhatsApp by uploading the audio file.
        
        Args:
            to (str): Recipient WhatsApp ID (phone number with country code)
            audio_path (str): Local path to the audio file
            context_message_id (str, optional): Message ID to reply to (creates threaded reply)
            
        Returns:
            dict: Response from WhatsApp API, or None if send failed
        """
        try:
            access_token = os.getenv('ACCESS_TOKEN')
            phone_number_id = os.getenv('PHONE_NUMBER_ID')
            version = os.getenv('VERSION', 'v23.0')
            
            if not access_token or not phone_number_id:
                logger.error("❌ ACCESS_TOKEN or PHONE_NUMBER_ID not found in environment variables")
                return None
            
            logger.info(f"📤 Uploading and sending audio message to {to}")
            logger.info(f"📁 Audio file: {audio_path}")
            
            # Step 1: Upload media to WhatsApp
            upload_url = f"https://graph.facebook.com/{version}/{phone_number_id}/media"
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            with open(audio_path, 'rb') as audio_file:
                files = {
                    'file': ('voice.mp3', audio_file, 'audio/mpeg'),
                    'messaging_product': (None, 'whatsapp'),
                    'type': (None, 'audio/mpeg')
                }
                
                logger.info(f"⬆️ Uploading audio to WhatsApp...")
                upload_response = requests.post(
                    upload_url,
                    headers=headers,
                    files=files,
                    timeout=60
                )
                upload_response.raise_for_status()
            
            upload_result = upload_response.json()
            media_id = upload_result.get('id')
            
            if not media_id:
                logger.error(f"❌ No media ID in upload response: {upload_result}")
                return None
            
            logger.info(f"✅ Audio uploaded! Media ID: {media_id}")
            
            # Step 2: Send message with media ID
            message_url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
            
            message_data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "audio",
                "audio": {
                    "id": media_id
                }
            }
            
            # Add context for reply threading if message_id provided
            if context_message_id:
                message_data["context"] = {
                    "message_id": context_message_id
                }
                logger.info(f"💬 Replying to message: {context_message_id}")
            
            headers["Content-Type"] = "application/json"
            
            logger.info(f"📨 Sending audio message with media ID...")
            send_response = requests.post(
                message_url,
                headers=headers,
                json=message_data,
                timeout=30
            )
            send_response.raise_for_status()
            
            result = send_response.json()
            logger.info(f"✅ Audio message sent successfully: {result}")
            
            return result
            
        except requests.Timeout:
            logger.error("⏱️ Timeout while sending audio message")
            return None
        except requests.RequestException as e:
            logger.error(f"❌ Failed to send audio message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error sending audio: {e}")
            return None
    
    def cleanup_temp_files(self, file_path):
        """
        Clean up temporary audio files.
        
        Args:
            file_path (str): Path to the file to delete
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"🗑️ Cleaned up temp file: {file_path}")
        except Exception as e:
            logger.error(f"⚠️ Failed to cleanup temp file {file_path}: {e}")
    
    def _get_extension_from_mime(self, mime_type):
        """
        Get file extension from MIME type.
        
        Args:
            mime_type (str): MIME type string
            
        Returns:
            str: File extension with dot (e.g., '.ogg', '.mp3')
        """
        mime_map = {
            'audio/ogg': '.ogg',
            'audio/mpeg': '.mp3',
            'audio/mp4': '.m4a',
            'audio/amr': '.amr',
            'audio/wav': '.wav',
        }
        return mime_map.get(mime_type, '.ogg')


# Convenience functions for backward compatibility
_handler = None

def get_voice_handler():
    """Get or create the voice handler singleton."""
    global _handler
    if _handler is None:
        _handler = VoiceMessageHandler()
    return _handler


def download_audio_from_whatsapp(media_id):
    """Download audio from WhatsApp. See VoiceMessageHandler.download_audio_from_whatsapp()"""
    return get_voice_handler().download_audio_from_whatsapp(media_id)


def transcribe_audio(file_path):
    """Transcribe audio file. See VoiceMessageHandler.transcribe_audio()"""
    return get_voice_handler().transcribe_audio(file_path)


def synthesize_speech(text):
    """Convert text to speech. See VoiceMessageHandler.synthesize_speech()"""
    return get_voice_handler().synthesize_speech(text)


def send_audio_reply(to, audio_path, context_message_id=None):
    """Send audio message via WhatsApp. See VoiceMessageHandler.send_audio_reply()"""
    return get_voice_handler().send_audio_reply(to, audio_path, context_message_id)
