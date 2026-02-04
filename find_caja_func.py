
def find_gestionar_caja():
    with open('app/routes.py', 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if 'def gestionar_caja' in line:
                print(f"Found at line {i+1}")
                return i+1
    return 0

line = find_gestionar_caja()
if line:
    print(f"Reading context around line {line}")
