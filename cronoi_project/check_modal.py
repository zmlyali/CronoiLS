import re

with open(r'C:\PROJECTS\cronoi_project\cronoi_project\frontend\Cronoi_LS_v2.html', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Split by script tags
parts = re.split(r'<script[^>]*>|</script>', content)

for i, part in enumerate(parts):
    is_html = (i % 2 == 0)
    label = "HTML" if is_html else "JS"
    
    if is_html and '${title}' in part:
        # Find the approximate line
        before = content[:content.find(part[:min(50, len(part))])]
        line_num = before.count('\n') + 1
        idx = part.index('${title}')
        ctx = part[max(0,idx-120):idx+120].replace('\n', '\\n')
        print(f"!! FOUND raw template literal in HTML section #{i}, ~line {line_num}")
        print(f"   Context: {ctx[:240]}")
        print()
    
    if is_html and 'vehicleDefForm' in part:
        before = content[:content.find(part[:min(50, len(part))])]
        line_num = before.count('\n') + 1
        idx = part.index('vehicleDefForm')
        ctx = part[max(0,idx-80):idx+80].replace('\n', '\\n')
        print(f"!! FOUND vehicleDefForm in HTML section #{i}, ~line {line_num}")
        print(f"   Context: {ctx}")
        print()

    if is_html and 'Kasa' in part and 'Maliyet' in part:
        print(f"!! FOUND modal-like content in HTML section #{i}")
        idx = part.index('Kasa')
        ctx = part[max(0,idx-60):idx+60].replace('\n', '\\n')
        print(f"   Context: {ctx}")
        print()

print("Done checking.")
