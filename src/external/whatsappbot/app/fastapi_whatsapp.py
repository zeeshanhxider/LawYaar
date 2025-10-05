import logging
import json
import asyncio
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse

from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

router = APIRouter()


# Root webhook endpoints (for Meta Developer Console)
@router.get("/webhook")
async def verify_root(request: Request):
    """Root webhook verification endpoint for Meta"""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logging.info(f"Root verification request: mode={mode}, token={token}, challenge={challenge}")

    import os
    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logging.info("ROOT WEBHOOK_VERIFIED")
            return PlainTextResponse(challenge or "", status_code=200)
        else:
            logging.warning("ROOT VERIFICATION_FAILED")
            raise HTTPException(status_code=403, detail="Verification failed")
    else:
        raise HTTPException(status_code=400, detail="Missing parameters")


@router.post("/webhook")
async def webhook_post_root(request: Request, background_tasks: BackgroundTasks):
    """Root webhook message endpoint for Meta"""
    logging.info("ROOT WEBHOOK POST REQUEST RECEIVED")
    try:
        body = await request.json()
    except Exception:
        logging.error("Invalid JSON in webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logging.info(f"Root webhook payload received: {json.dumps(body)[:1000]}")

    # Check for status updates and ignore them (delivered, read, sent, etc.)
    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
    if "statuses" in value:
        logging.info("📊 Received WhatsApp status update (delivered/read/sent) - ignoring")
        return JSONResponse({"status": "status_update_ignored"}, status_code=200)

    # Quick legacy checks for actual messages
    if body.get("object"):
        if is_valid_whatsapp_message(body):
            # Process message in background to avoid blocking
            background_tasks.add_task(process_whatsapp_message, body)
            return JSONResponse({"status": "success"}, status_code=200)
        else:
            return JSONResponse({"status": "ignored"}, status_code=200)
    
    return JSONResponse({"status": "not processed"}, status_code=404)


# Legacy endpoints (for backwards compatibility)
@router.get("/external/whatsappbot/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logging.info(f"Verification request: mode={mode}, token={token}, challenge={challenge}")

    # Use environment variable VERIFY_TOKEN if present
    import os

    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            logging.info("WEBHOOK_VERIFIED")
            return PlainTextResponse(challenge or "", status_code=200)
        else:
            logging.warning("VERIFICATION_FAILED")
            raise HTTPException(status_code=403, detail="Verification failed")
    else:
        raise HTTPException(status_code=400, detail="Missing parameters")


@router.post("/external/whatsappbot/webhook")
async def webhook_post(request: Request, background_tasks: BackgroundTasks):
    logging.info("WEBHOOK POST REQUEST RECEIVED")
    try:
        body = await request.json()
    except Exception:
        logging.error("Invalid JSON in webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logging.info(f"Webhook payload received: {json.dumps(body)[:1000]}")

    # Quick legacy checks for status updates
    value = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
    if "statuses" in value:
        logging.info("Received a WhatsApp status update - ignoring")
        return JSONResponse({"status": "ok"})

    try:
        is_valid = is_valid_whatsapp_message(body)
        logging.info(f"is_valid_whatsapp_message = {is_valid}")
        if is_valid:
            # Process message in background to avoid blocking
            background_tasks.add_task(process_whatsapp_message, body)
            return JSONResponse({"status": "ok"})
        else:
            logging.warning("Not a WhatsApp API event")
            raise HTTPException(status_code=404, detail="Not a WhatsApp API event")
    except Exception as e:
        logging.exception(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
