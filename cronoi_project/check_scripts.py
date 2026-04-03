with open(r'C:\PROJECTS\cronoi_project\cronoi_project\frontend\Cronoi_LS_v2.html', 'r', encoding='utf-8-sig') as f:
    content = f.read()

import re

# Find ALL script tags with line numbers
for m in re.finditer(r'<script[^>]*>', content):
    line = content[:m.start()].count('\n') + 1
    tag = m.group()
    # Check if this is an inline or src script
    next_50 = content[m.end():m.end()+60].strip()
    print(f"Line {line}: {tag}")
    if '</script>' in content[m.end():m.end()+20]:
        print(f"  -> EMPTY (immediately closed)")
    elif 'src=' in tag:
        print(f"  -> External CDN")
    else:
        # Find closing </script>
        close = content.index('</script>', m.end())
        js_len = close - m.end()
        js_lines = content[m.end():close].count('\n') + 1
        print(f"  -> Inline JS: {js_len} chars, {js_lines} lines")
        print(f"  -> First 80: {content[m.end():m.end()+80].strip()[:80]}")
