"""
Urdu PDF Helper Module
Provides utilities for proper Urdu text rendering in PDFs
"""
import logging
import re

logger = logging.getLogger(__name__)

# Try to import Urdu text processing libraries
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    URDU_SUPPORT = True
    logger.info("✅ Arabic reshaper and BiDi support loaded successfully")
except ImportError as e:
    URDU_SUPPORT = False
    logger.warning(f"⚠️ Urdu text shaping libraries not available: {e}")
    logger.warning("Install with: pip install arabic-reshaper python-bidi")


def has_urdu_text(text):
    """
    Check if text contains Urdu/Arabic characters.
    
    Args:
        text: String to check
        
    Returns:
        bool: True if text contains Urdu/Arabic characters
    """
    if not text:
        return False
    
    # Check for Arabic/Urdu Unicode ranges
    urdu_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
    return urdu_chars > 0


def reshape_urdu_text(text):
    """
    Reshape Urdu/Arabic text for proper rendering in PDF.
    This fixes the issue of disconnected letters and ensures proper word formation.
    
    Args:
        text: String containing Urdu/Arabic text
        
    Returns:
        str: Reshaped text ready for PDF rendering
    """
    if not text or not URDU_SUPPORT:
        return text
    
    try:
        # Check if text contains Arabic/Urdu characters
        if not has_urdu_text(text):
            return text
        
        # Configure reshaper for Urdu (which uses Arabic script)
        configuration = {
            'delete_harakat': False,  # Keep diacritics
            'support_ligatures': True,  # Enable ligatures for proper word formation
            'shift_harakat_position': False,
            'use_unshaped_instead_of_isolated': False,
        }
        
        # Reshape the text to connect letters properly
        reshaped_text = arabic_reshaper.reshape(text, configuration=configuration)
        
        # Apply bidirectional algorithm for right-to-left display
        bidi_text = get_display(reshaped_text)
        
        return bidi_text
        
    except Exception as e:
        logger.warning(f"Error reshaping Urdu text: {e}")
        return text


def reshape_html_with_urdu(html_text):
    """
    Process HTML-like text (used in ReportLab) to reshape any Urdu content
    while preserving HTML tags.
    
    Args:
        html_text: HTML-formatted text that may contain Urdu
        
    Returns:
        str: Processed text with reshaped Urdu content
    """
    if not html_text or not URDU_SUPPORT:
        return html_text
    
    try:
        # Split by HTML tags to process only text content
        # Pattern to match HTML tags
        tag_pattern = r'(<[^>]+>)'
        parts = re.split(tag_pattern, html_text)
        
        reshaped_parts = []
        for part in parts:
            # If it's an HTML tag, keep it as is
            if part.startswith('<') and part.endswith('>'):
                reshaped_parts.append(part)
            else:
                # Otherwise, reshape if it contains Urdu
                if has_urdu_text(part):
                    reshaped_parts.append(reshape_urdu_text(part))
                else:
                    reshaped_parts.append(part)
        
        return ''.join(reshaped_parts)
        
    except Exception as e:
        logger.warning(f"Error processing HTML with Urdu: {e}")
        return html_text


def create_urdu_paragraph(text, escape_func=None):
    """
    Prepare text for use in ReportLab Paragraph, with proper Urdu reshaping.
    
    Args:
        text: Raw text that may contain Urdu
        escape_func: Optional XML escape function to apply
        
    Returns:
        str: Text ready for Paragraph creation
    """
    if not text:
        return text
    
    # First escape if needed
    if escape_func:
        text = escape_func(text)
    
    # Then reshape Urdu content while preserving any HTML tags
    if has_urdu_text(text):
        text = reshape_html_with_urdu(text)
    
    return text
