
import os

def search_recursive(directory, search_term):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(('.py', '.html')):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f):
                            if search_term in line:
                                print(f"Found '{search_term}' in {filepath} at line {i+1}")
                                return # One match per file is enough to locate it
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")

search_recursive('app', 'pagina_caja')
