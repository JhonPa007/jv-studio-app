import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get('GEMINI_API_KEY')
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

try:
    response = requests.get(url)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        models = response.json().get('models', [])
        for m in models:
            print(f"- {m['name']} (v1beta)")
    else:
        print(response.text)
except Exception as e:
    print(f"Error: {e}")

url_v1 = f"https://generativelanguage.googleapis.com/v1/models?key={api_key}"
try:
    response = requests.get(url_v1)
    print(f"\nStatus v1: {response.status_code}")
    if response.status_code == 200:
        models = response.json().get('models', [])
        for m in models:
            print(f"- {m['name']} (v1)")
except Exception as e:
    print(f"Error v1: {e}")
