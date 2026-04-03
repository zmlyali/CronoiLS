with open(r'C:\PROJECTS\cronoi_project\cronoi_project\frontend\Cronoi_LS_v2.html', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()

# Chrome reports the line number relative to the HTML file start
# The script tag starts at line 1989 (0-indexed: 1988)
# Let's find the exact <script> start for the main inline block
script_start = None
for i, line in enumerate(lines):
    if line.strip() == '<script>' and i > 1987:
        script_start = i
        break

print(f"Main <script> at line {script_start + 1}")

# The error at line 5090 means HTML line 5090
# Chrome counts from HTML line 1, so:
error_html_line = 5090
# The JS within the <script> tag runs from script_start+1 to </script>

# Extract JS up to this line
js_lines = []
for i in range(script_start + 1, min(error_html_line, len(lines))):
    if '</script>' in lines[i]:
        break
    js_lines.append(lines[i])

print(f"Extracted {len(js_lines)} JS lines (HTML {script_start+2} to {script_start+1+len(js_lines)})")

# Write partial JS and try to parse with Node
import subprocess, tempfile, os
partial_js = ''.join(js_lines)
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
    tmp.write(partial_js)
    tmp_path = tmp.name

result = subprocess.run(['node', '--check', tmp_path], capture_output=True, text=True)
print(f"Node parse partial (first {len(js_lines)} lines): {'OK' if result.returncode == 0 else 'ERROR'}")
if result.returncode != 0:
    print(f"  {result.stderr.strip()[:300]}")

# Now try FULL JS block
full_js_lines = []
for i in range(script_start + 1, len(lines)):
    if '</script>' in lines[i]:
        break
    full_js_lines.append(lines[i])

full_js = ''.join(full_js_lines)
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp2:
    tmp2.write(full_js)
    tmp_path2 = tmp2.name

result2 = subprocess.run(['node', '--check', tmp_path2], capture_output=True, text=True)
print(f"Node parse full ({len(full_js_lines)} lines): {'OK' if result2.returncode == 0 else 'ERROR'}")
if result2.returncode != 0:
    print(f"  {result2.stderr.strip()[:300]}")

# Also try parsing just the first 3100 lines (line 5090 - 1989 = 3101 lines offset)
partial2_js = ''.join(full_js_lines[:3101])
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp3:
    tmp3.write(partial2_js)
    tmp_path3 = tmp3.name

result3 = subprocess.run(['node', '--check', tmp_path3], capture_output=True, text=True)
print(f"Node parse first 3101 JS lines: {'OK' if result3.returncode == 0 else 'ERROR'}")
if result3.returncode != 0:
    print(f"  {result3.stderr.strip()[:300]}")

# Binary search for the breaking line
if result2.returncode == 0 and result3.returncode != 0:
    lo, hi = 1, 3101
    while lo < hi:
        mid = (lo + hi) // 2
        test_js = ''.join(full_js_lines[:mid])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmpx:
            tmpx.write(test_js)
            tmpx_path = tmpx.name
        r = subprocess.run(['node', '--check', tmpx_path], capture_output=True, text=True)
        os.unlink(tmpx_path)
        if r.returncode == 0:
            lo = mid + 1
        else:
            hi = mid
    print(f"\nBreaking at JS line {lo} (HTML line ~{script_start + 1 + lo})")
    print(f"  Line content: {full_js_lines[lo-1].rstrip()[:120]}")
    # Show context
    for i in range(max(0, lo-5), min(lo+5, len(full_js_lines))):
        marker = ">>>" if i == lo-1 else "   "
        print(f"  {marker} JS:{i+1} | {full_js_lines[i].rstrip()[:120]}")

os.unlink(tmp_path)
os.unlink(tmp_path2)
os.unlink(tmp_path3)
