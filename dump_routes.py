
from app import create_app

try:
    app = create_app()
    with open('routes_dump.txt', 'w') as f:
        for rule in app.url_map.iter_rules():
            f.write(f"Endpoint: {rule.endpoint}, URL: {rule.rule}\n")
    print("Routes dumped to routes_dump.txt")
except Exception as e:
    print(f"Error: {e}")
