
import os

def find_in_file(filename, search_term):
    encodings = ['utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(filename, 'r', encoding=enc) as f:
                for i, line in enumerate(f):
                    if search_term in line:
                        print(f"Found '{search_term}' in {filename} at line {i+1} (encoding: {enc})")
                        return
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            break

find_in_file('app/routes.py', 'def pagina_caja')
find_in_file('app/routes_finanzas.py', 'def pagina_caja')
find_in_file('app/routes.py', 'finanzas/pagina_caja.html')
