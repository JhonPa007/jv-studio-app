
import os

def find_in_file(filename, search_term):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if search_term in line:
                    print(f"Found '{search_term}' in {filename} at line {i+1}")
                    print(f"Line content: {line.strip()}")
    except Exception as e:
        print(f"Error: {e}")

find_in_file('app/routes.py', 'def pagina_caja')
find_in_file('app/routes.py', 'pagina_caja.html')
