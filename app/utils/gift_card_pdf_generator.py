import os
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from flask import current_app

def generate_gift_card_pdf(code, amount, recipient_name, from_name=None, package_name=None, services_text=None, expiration_date=None, description=None):
    """
    Generates a Gift Card PDF with a specific business card size (85mm x 45mm).
    Returns the absolute path to the generated PDF.
    """
    try:
        static_folder = current_app.static_folder
        output_filename = f"gift_card_{code}.pdf"
        output_dir = os.path.join(static_folder, 'pdf', 'gift_cards')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)
        
        # Dimensions: 85mm x 45mm
        from reportlab.lib.units import mm
        width, height = (85 * mm, 45 * mm)
        
        c = canvas.Canvas(output_path, pagesize=(width, height))
        
        # --- Background ---
        bg_image_path = os.path.join(static_folder, 'img', 'gift_card_bg.jpg')
        if os.path.exists(bg_image_path):
            c.drawImage(bg_image_path, 0, 0, width=width, height=height)
        else:
            # Fallback if image not found (shouldn't happen based on plan)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.rect(0, 0, width, height, fill=1)
        
        # --- Fonts ---
        # Register fonts
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

        # --- Content Layout (Scaling for 85x45mm) ---
        
        # 1. Header Row
        # "JV STUDIO" (Top Left)
        c.setFillColor(colors.white) # or slightly off-white
        c.setFont(font_main, 8) 
        c.drawString(3 * mm, height - 6 * mm, "JV STUDIO")

        # "GIFT CARD" (Top Center)
        c.setFillColor(colors.gold)
        c.setFont(font_main, 10)
        c.drawCentredString(width / 2, height - 6 * mm, "GIFT CARD")

        # "CÓDIGO: ..." (Top Right)
        c.setFillColor(colors.white)
        c.setFont(font_reg, 5) # Small
        c.drawRightString(width - 3 * mm, height - 6 * mm, f"CÓDIGO: {code}")

        # 2. Main Title (Service/Package) - CENTER
        c.setFillColor(colors.gold)
        c.setFont(font_main, 14) # Large
        
        main_text = ""
        if package_name:
            main_text = package_name.upper()
            if len(main_text) > 20: c.setFont(font_main, 11)
        else:
            main_text = f"S/ {float(amount):.2f}"
            
        c.drawCentredString(width / 2, height / 2 + 2 * mm, main_text)
        
        # 3. Description - CENTER Below Title
        c.setFillColor(colors.white)
        c.setFont(font_reg, 6)
        
        text_to_display = description if description else services_text
        
        if package_name and text_to_display:
             # Simple wrapping logic for description
             # Split into lines if too long? For 85mm width, maybe ~40-50 chars max per line with this font?
             # Let's try a simple wrap
             from reportlab.lib.utils import simpleSplit
             # Available width roughly 80mm
             avail_width = 75 * mm
             lines = simpleSplit(text_to_display, font_reg, 6, avail_width)
             
             y_offset = height / 2 - 2 * mm
             for line in lines[:3]: # Limit to 3 lines max
                 c.drawCentredString(width / 2, y_offset, line)
                 y_offset -= 2.5 * mm
        else:
             pass

        # 4. Custom Message ("Para mi hermanito...")
        # We don't have a specific field for this message in the function signature yet,
        # but the reference has it. For now, we'll skip the hardcoded quote 
        # or add a placeholder if desired. 
        # c.setFont("Helvetica-Oblique", 6)
        # c.setFillColor(colors.gold)
        # c.drawString(3 * mm, height / 2 - 8 * mm, '"Para mi hermanito con mucho cariño"')

        # 5. Footer Area
        c.setFont(font_reg, 6)
        c.setFillColor(colors.white)
        
        # De: ...
        if from_name:
            c.drawString(3 * mm, 7 * mm, f"De: {from_name}")
            
        # Para: ...
        c.drawString(3 * mm, 3 * mm, f"Para: {recipient_name}")

        # Vence: ...
        if expiration_date:
            c.drawRightString(width - 3 * mm, 7 * mm, f"VENCE: {expiration_date}")

        # Validation Text
        c.setFont(font_reg, 4)
        c.drawRightString(width - 3 * mm, 3 * mm, "VÁLIDO PARA CANJE EN JV STUDIO")

        c.save()
        return output_path
        
    except Exception as e:
        print(f"Error creating PDF: {e}")
        return None
