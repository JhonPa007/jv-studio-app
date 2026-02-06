import os
from PIL import Image, ImageDraw, ImageFont
from flask import current_app

def generate_gift_card_image(code, amount, recipient_name, package_name=None, services_text=None):
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
        
        # 1. MAIN CONTENT (Amount OR Package Name)
        try:
            font_main = ImageFont.truetype(font_path_bold, 80)
        except:
            font_main = ImageFont.load_default()
        
        if package_name:
            # PACKAGE MODE
            text_main = str(package_name).upper()
            # If name is too long, we might need to reduce font size (simple heuristic)
            if len(text_main) > 20: 
                try: font_main = ImageFont.truetype(font_path_bold, 60)
                except: pass
        else:
            # MONEY MODE
            text_main = f"S/ {float(amount):.2f}"
        
        # Calculate text size
        try:
            _, _, w_main, h_main = draw.textbbox((0, 0), text_main, font=font_main)
        except AttributeError:
            w_main, h_main = draw.textsize(text_main, font=font_main)
             
        # Center horizontally, slightly above center vertically
        x_main = (width - w_main) / 2
        y_main = (height / 2) - h_main - 30 
        
        draw.text((x_main, y_main), text_main, font=font_main, fill="#D4AF37") # Gold color

        # 2. SUB CONTENT (Services List OR Recipient)
        # We will put Recipient always, but if there are services, we put them below main text first
        
        current_y = y_main + h_main + 20
        
        # If Package: Show Services
        if package_name and services_text:
            try:
                font_services = ImageFont.truetype(font_path_reg, 24)
            except:
                font_services = ImageFont.load_default()
            
            # Truncate if too long (very basic)
            if len(services_text) > 60:
                services_text = services_text[:57] + "..."
                
            try:
                _, _, w_srv, h_srv = draw.textbbox((0, 0), services_text, font=font_services)
            except AttributeError:
                w_srv, h_srv = draw.textsize(services_text, font=font_services)
                
            x_srv = (width - w_srv) / 2
            draw.text((x_srv, current_y), services_text, font=font_services, fill="white")
            current_y += h_srv + 10

        # 3. RECIPIENT (Always show, below everything)
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
            # Use current_y calculated above
            draw.text((x_rec, current_y), text_recipient, font=font_recipient, fill="white")

        # 4. CODE (Bottom, White, Monospace-ish)
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
