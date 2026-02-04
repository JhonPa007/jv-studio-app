
from app import create_app
import sys

# Mocking stuff to make it importable if needed, but create_app should work if env is set
# We just want to inspect the url_map
try:
    app = create_app()
    print("Listing all routes:")
    for rule in app.url_map.iter_rules():
        if 'caja' in rule.rule or 'pagina_caja' in rule.endpoint:
            print(f"Endpoint: {rule.endpoint}, URL: {rule.rule}")
except Exception as e:
    print(f"Error inspecting routes: {e}")
