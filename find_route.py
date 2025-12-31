
with open('d:/JV_Studio/jv_studio_app/app/routes.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        if 'agenda_dia_data' in line:
            print(f"Found at line {i}: {line.strip()}")
