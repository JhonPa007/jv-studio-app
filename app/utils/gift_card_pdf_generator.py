import os
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from flask import current_app

def generate_gift_card_pdf(code, amount, recipient_name, from_name=None, package_name=None, services_text=None, expiration_date=None):
    """
    Generates a Gift Card PDF.
    Returns the absolute path to the generated PDF.
    """
    try:
        static_folder = current_app.static_folder
        output_filename = f"gift_card_{code}.pdf"
        output_dir = os.path.join(static_folder, 'pdf', 'gift_cards')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)
        
        # Dimensions
        width, height = landscape(letter) # Standard letter landscape
        
        c = canvas.Canvas(output_path, pagesize=landscape(letter))
        
        # --- Background / Design ---
        # Very simple design: Gold border, dark background
        c.setFillColorRGB(0.1, 0.1, 0.1) # Dark Gray
        c.rect(0, 0, width, height, fill=1)
        
        # Inner Card Area (Centered)
        card_w = 8 * inch
        card_h = 4 * inch
        x_start = (width - card_w) / 2
        y_start = (height - card_h) / 2
        
        c.setStrokeColor(colors.gold)
        c.setLineWidth(5)
        c.rect(x_start, y_start, card_w, card_h, stroke=1, fill=0)
        
        # --- Fonts ---
        # Register fonts if available, else use standard
        font_main = "Helvetica-Bold"
        font_reg = "Helvetica"
        
        font_path_bold = os.path.join(static_folder, 'fonts', 'AGENCYB.TTF')
        font_path_reg = os.path.join(static_folder, 'fonts', 'AGENCYR.TTF')
        
        if os.path.exists(font_path_bold):
            pdfmetrics.registerFont(TTFont('AgencyFB-Bold', font_path_bold))
            font_main = 'AgencyFB-Bold'
            
        if os.path.exists(font_path_reg):
            pdfmetrics.registerFont(TTFont('AgencyFB-Reg', font_path_reg))
            font_reg = 'AgencyFB-Reg'

        # --- Content ---
        
        # 1. Main Title (Value or Package)
        c.setFillColor(colors.gold)
        c.setFont(font_main, 60)
        
        if package_name:
            main_text = package_name.upper()
            if len(main_text) > 20: c.setFont(font_main, 40)
        else:
            main_text = f"S/ {float(amount):.2f}"
            
        c.drawCentredString(width / 2, y_start + card_h - 1.2 * inch, main_text)
        
        # 2. Services or Subtitle
        c.setFillColor(colors.white)
        c.setFont(font_reg, 18)
        
        current_y = y_start + card_h - 2.2 * inch
        
        if package_name and services_text:
            # Wrap text if needed? specific logic for now just simple
            c.drawCentredString(width / 2, current_y, services_text)
            current_y -= 0.5 * inch
        
        # 3. Recipient & From
        c.setFont(font_reg, 24)
        c.drawCentredString(width / 2, current_y, f"Para: {recipient_name}")
        
        if from_name:
            current_y -= 0.4 * inch
            c.setFont(font_reg, 18)
            c.drawCentredString(width / 2, current_y, f"De: {from_name}")

        # 4. Code & Expiration
        c.setFillColor(colors.white)
        c.setFont(font_main, 20)
        
        # Code bottom center
        c.drawCentredString(width / 2, y_start + 0.8 * inch, f"CÓDIGO: {code}")
        
        if expiration_date:
            c.setFont(font_reg, 12)
            c.drawCentredString(width / 2, y_start + 0.4 * inch, f"Vence: {expiration_date}")

        c.save()
        return output_path
        
    except Exception as e:
        print(f"Error creating PDF: {e}")
        return None
