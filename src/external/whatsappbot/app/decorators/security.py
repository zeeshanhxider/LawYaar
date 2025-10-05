from functools import wraps
from flask import current_app, jsonify, request
import logging
import hashlib
import hmac


def validate_signature(payload, signature):
    """
    Validate the incoming payload's signature against our expected signature
    """
    # Use the App Secret to hash the payload
    app_secret = current_app.config.get("APP_SECRET", "")
    
    if not app_secret:
        logging.error("APP_SECRET is not configured!")
        return False
    
    expected_signature = hmac.new(
        bytes(app_secret, "utf-8"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Debug logging
    logging.info(f"Expected signature: {expected_signature[:20]}...")
    logging.info(f"Received signature: {signature[:20]}...")
    
    # Check if the signature matches
    result = hmac.compare_digest(expected_signature, signature)
    logging.info(f"Signature match result: {result}")
    return result


def signature_required(f):
    """
    Decorator to ensure that the incoming requests to our webhook are valid and signed with the correct signature.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        signature = signature_header[7:] if signature_header.startswith("sha256=") else signature_header  # Removing 'sha256='
        
        payload = request.data.decode("utf-8")
        
        # Debug logging
        logging.info(f"Received signature header: {signature_header[:20]}..." if signature_header else "No signature header")
        logging.info(f"APP_SECRET configured: {bool(current_app.config.get('APP_SECRET'))}")
        logging.info(f"Payload length: {len(payload)}")
        
        if not signature:
            logging.warning("No signature found in request headers!")
            return jsonify({"status": "error", "message": "Missing signature"}), 403
            
        if not validate_signature(payload, signature):
            logging.info("Signature verification failed!")
            return jsonify({"status": "error", "message": "Invalid signature"}), 403
            
        logging.info("✅ Signature verified successfully!")
        return f(*args, **kwargs)

    return decorated_function
