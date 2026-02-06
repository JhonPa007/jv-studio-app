import os
from PIL import Image, ImageDraw, ImageFont
from flask import current_app

def generate_gift_card_image(code, amount, recipient_name):
    """
    Generates a Gift Card image by overlaying text on a base template.
    Returns the web-accessible path to the generated image.
    """
    try:
        # Paths
        static_folder = current_app.static_folder
        template_path = os.path.join(static_folder, 'img', 'gift_cards', 'plantilla_base_giftcard.png')
        output_filename = f"gift_card_{code}.jpg"
        output_path = os.path.join(static_folder, 'img', 'gift_cards', output_filename)
        font_path_bold = os.path.join(static_folder, 'fonts', 'AGENCYB.TTF')
        font_path_reg = os.path.join(static_folder, 'fonts', 'AGENCYR.TTF')
        
        # Check if template exists
        if not os.path.exists(template_path):
            # Create a fallback placeholder image if template is missing
            img = Image.new('RGB', (800, 400), color = '#1a1a1a')
            draw = ImageDraw.Draw(img)
            # Draw border
            draw.rectangle([10, 10, 790, 390], outline="gold", width=5)
            print("Template not found, using fallback background.")
        else:
            img = Image.open(template_path).convert('RGB')
            draw = ImageDraw.Draw(img)

        # Image Dimensions
        width, height = img.size

        # --- CONFIGURATION (Adjust coordinates based on actual template) ---
        # Assuming 800x400 approx or similar ratio
        
        # 1. AMOUNT (Center, Gold, Elegant)
        try:
            font_amount = ImageFont.truetype(font_path_bold, 80)
        except:
            font_amount = ImageFont.load_default()
        
        text_amount = f"S/ {float(amount):.2f}"
        
        # Calculate text size (new method for Pillow >= 10, fallback for older)
        try:
            _, _, w_amt, h_amt = draw.textbbox((0, 0), text_amount, font=font_amount)
        except AttributeError:
             w_amt, h_amt = draw.textsize(text_amount, font=font_amount)
             
        # Center horizontally, slightly above center vertically
        x_amt = (width - w_amt) / 2
        y_amt = (height / 2) - h_amt - 20 
        
        draw.text((x_amt, y_amt), text_amount, font=font_amount, fill="#D4AF37") # Gold color

        # 2. RECIPIENT (Below amount, smaller)
        if recipient_name:
            try:
                font_recipient = ImageFont.truetype(font_path_reg, 30)
            except:
                font_recipient = ImageFont.load_default()
            
            text_recipient = f"Para: {recipient_name}"
            try:
                 _, _, w_rec, h_rec = draw.textbbox((0, 0), text_recipient, font=font_recipient)
            except AttributeError:
                 w_rec, h_rec = draw.textsize(text_recipient, font=font_recipient)
            
            x_rec = (width - w_rec) / 2
            y_rec = y_amt + h_amt + 20
            
            draw.text((x_rec, y_rec), text_recipient, font=font_recipient, fill="white")

        # 3. CODE (Bottom, White, Monospace-ish)
        try:
            font_code = ImageFont.truetype(font_path_bold, 24)
        except:
            font_code = ImageFont.load_default()
            
        text_code = f"CÓDIGO: {code}"
        try:
             _, _, w_code, h_code = draw.textbbox((0, 0), text_code, font=font_code)
        except AttributeError:
             w_code, h_code = draw.textsize(text_code, font=font_code)
             
        # Bottom center
        x_code = (width - w_code) / 2
        y_code = height - h_code - 30
        
        draw.text((x_code, y_code), text_code, font=font_code, fill="white")

        # Save
        img.save(output_path, quality=95)
        
        return f"/static/img/gift_cards/{output_filename}"

    except Exception as e:
        print(f"Error generating gift card image: {e}")
        return None
