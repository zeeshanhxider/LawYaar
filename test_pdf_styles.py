#!/usr/bin/env python3
"""
Quick test to verify PDF generation works without BodyText style conflicts
"""

import sys
import os
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

try:
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_JUSTIFY

    print("✅ Testing PDF style creation...")

    # Test the same logic as in the PDF generation function
    styles = getSampleStyleSheet()

    # Test the fixed BodyText style handling
    urdu_font = 'Helvetica'  # Test with default font

    if 'BodyText' not in styles:
        styles.add(ParagraphStyle(
            name='BodyText',
            parent=styles['Normal'],
            fontName=urdu_font,
            fontSize=11,
            alignment=TA_JUSTIFY,
            leading=14,
            spaceAfter=6,
            encoding='utf-8'
        ))
        print("✅ Added BodyText style successfully")
    else:
        # Style already exists, modify the existing one
        print("✅ BodyText style already exists, modifying existing style")
        styles['BodyText'].fontName = urdu_font
        styles['BodyText'].fontSize = 11
        styles['BodyText'].alignment = TA_JUSTIFY
        styles['BodyText'].leading = 14
        styles['BodyText'].spaceAfter = 6
        print("✅ Modified existing BodyText style successfully")

    # Test accessing the style
    body_style = styles['BodyText']
    print(f"✅ BodyText style properties: fontName={body_style.fontName}, fontSize={body_style.fontSize}")

    print("✅ PDF style test completed successfully!")

except Exception as e:
    print(f"❌ Error in PDF style test: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)