import logging
import json
from flask import Blueprint, request, jsonify, current_app

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

webhook_blueprint = Blueprint("webhook", __name__)


def handle_message():
    """
    Handle incoming webhook events from the WhatsApp API.
    """
    print("📍 ENTERED handle_message()")

    # Parse JSON safely
    body = request.get_json(silent=True)

    if not body:
        print("❌ No JSON body!")
        logging.error(f"No JSON body received. Raw data: {request.data}")
        return jsonify({"status": "error", "message": "Empty or invalid JSON"}), 400

    print(f"📦 Got body with keys: {list(body.keys())}")
    
    # Print the value to see what we're dealing with
    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
    print(f"🔍 Value keys: {list(value.keys())}")
    
    # Check if it's a status update or a message
    if "statuses" in value:
        print("✅ This is a STATUS UPDATE (delivery/read receipt) - IGNORING")
        logging.info("✅ Received a WhatsApp status update (delivery/read receipt).")
        return jsonify({"status": "ok"}), 200
    
    if "messages" in value:
        messages = value.get("messages", [])
        if messages:
            msg = messages[0]
            msg_type = msg.get("type")
            print(f"� MESSAGE RECEIVED - Type: '{msg_type}'")
            print(f"📨 Message keys: {list(msg.keys())}")
    
    logging.info(f"�📦 Webhook payload received: {json.dumps(body, indent=2)}")

    # Check if it's a WhatsApp status update (legacy check)
    if (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ):
        logging.info("✅ Received a WhatsApp status update (delivery/read receipt).")
        return jsonify({"status": "ok"}), 200

    try:
        print("🔍 Checking if valid WhatsApp message...")
        is_valid = is_valid_whatsapp_message(body)
        print(f"🔍 is_valid_whatsapp_message = {is_valid}")
        logging.info(f"🔍 is_valid_whatsapp_message = {is_valid}")
        
        if is_valid:
            print("✅ Valid! Calling process_whatsapp_message()...")
            logging.info("✅ Valid WhatsApp message. Processing...")
            process_whatsapp_message(body)
            print("✅ process_whatsapp_message() completed!")
            return jsonify({"status": "ok"}), 200
        else:
            print("❌ NOT VALID!")
            logging.warning("❌ Not a WhatsApp API event.")
            logging.warning(f"❌ Body structure: {json.dumps(body, indent=2)}")
            return jsonify({"status": "error", "message": "Not a WhatsApp API event"}), 404
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")
        logging.exception(f"❌ Error processing webhook: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# Required webhook verification for WhatsApp
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    logging.info(f"Verification request: mode={mode}, token={token}, challenge={challenge}")

    if mode and token:
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            logging.info("✅ WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            logging.warning("❌ VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verification failed"}), 403
    else:
        logging.warning("❌ MISSING_PARAMETER in verification")
        return jsonify({"status": "error", "message": "Missing parameters"}), 400


@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()


@webhook_blueprint.route("/webhook", methods=["POST"])
# @signature_required   # ⚠️ Temporarily disabled for testing - ENABLE THIS IN PRODUCTION!
def webhook_post():
    print("=" * 80)
    print("🔔 WEBHOOK POST REQUEST RECEIVED!")
    print("=" * 80)
    logging.info("=" * 80)
    logging.info("🔔 WEBHOOK POST REQUEST RECEIVED!")
    logging.info("=" * 80)
    return handle_message()
