"""Shim package to import the cloned `whatsappbot` directory.

This module adds the whatsappbot directory to sys.path and exposes its FastAPI
router as `router` when available.
"""
import os
import sys
import importlib
import logging

logger = logging.getLogger(__name__)

# Locate the sibling folder named 'whatsappbot'
this_dir = os.path.dirname(__file__)
external_parent = os.path.abspath(os.path.join(this_dir, ".."))
cloned_dir = os.path.join(external_parent, "whatsappbot")

router = None

if os.path.isdir(cloned_dir):
    if cloned_dir not in sys.path:
        sys.path.insert(0, cloned_dir)
    try:
        # The cloned project exposes its modules under `app` package
        mod = importlib.import_module("app.fastapi_whatsapp")
        router = getattr(mod, "router", None)
    except Exception as e:
        logger.warning(f"Could not import whatsappbot fastapi_whatsapp: {e}")
else:
    logger.warning(f"Whatsappbot directory not found at: {cloned_dir}")
