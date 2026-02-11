import sys
import os
from flask import Flask
from app.utils.gift_card_pdf_generator import generate_gift_card_pdf

# Mock Flask app
app = Flask(__name__)
# Adjust static folder to current dir for testing if needed, or assume it matches structure
app.static_folder = os.path.abspath('app/static')

def test_pdf():
    with app.app_context():
        pdf_path = generate_gift_card_pdf(
            code="JV-TEST-123",
            amount=100.00,
            recipient_name="Pablo",
            from_name="Anapaula",
            package_name="Corte & Estilo",
            services_text="Corte de cabello + Lavado + Masaje Capilar",
            expiration_date="28/11/2026"
        )
        
        if pdf_path and os.path.exists(pdf_path):
            print(f"SUCCESS: PDF generated at {pdf_path}")
            print(f"Size: {os.path.getsize(pdf_path)} bytes")
        else:
            print("FAILURE: PDF not generated")

if __name__ == "__main__":
    test_pdf()
