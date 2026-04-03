import re

with open(r'C:\PROJECTS\cronoi_project\cronoi_project\frontend\Cronoi_LS_v2.html', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Extract first script block
blocks = re.split(r'<script[^>]*>|</script>', content)
# blocks[0]=HTML, blocks[1]=first JS, blocks[2]=HTML, blocks[3]=second JS...
js = blocks[1]  # main script block

# Try to find where a syntax error might be using Node.js approach
# Instead, let's check brace/bracket/paren balance line by line
lines = js.split('\n')
print(f"Total JS lines in first script block: {len(lines)}")

# Track cumulative balance
brace = 0   # {}
paren = 0   # ()
bracket = 0 # []
in_string = None  # None, "'", '"', '`'
in_template_depth = 0  # for nested ${} inside ``
escape = False
in_line_comment = False
in_block_comment = False

last_good_line = 0

for line_idx, line in enumerate(lines):
    for i, ch in enumerate(line):
        if in_block_comment:
            if ch == '*' and i + 1 < len(line) and line[i+1] == '/':
                in_block_comment = False
            continue
        
        if in_line_comment:
            continue
            
        if escape:
            escape = False
            continue
            
        if ch == '\\' and in_string is not None:
            escape = True
            continue
            
        if in_string == '`':
            if ch == '`':
                in_string = None
            elif ch == '$' and i + 1 < len(line) and line[i+1] == '{':
                in_template_depth += 1
            continue
            
        if in_string is not None:
            if ch == in_string:
                in_string = None
            continue
        
        # Not in string or comment
        if ch == '/' and i + 1 < len(line):
            if line[i+1] == '/':
                in_line_comment = True
                continue
            if line[i+1] == '*':
                in_block_comment = True
                continue
        
        if ch == "'" or ch == '"':
            in_string = ch
            continue
        if ch == '`':
            in_string = '`'
            continue
            
        if ch == '{':
            brace += 1
        elif ch == '}':
            brace -= 1
            if in_template_depth > 0 and brace < 0:
                in_template_depth -= 1
                brace = 0
        elif ch == '(':
            paren += 1
        elif ch == ')':
            paren -= 1
        elif ch == '[':
            bracket += 1
        elif ch == ']':
            bracket -= 1
    
    in_line_comment = False
    
    # Check if balance goes negative
    if brace < -1 or paren < -2 or bracket < -1:
        html_line = line_idx + content[:content.index(js[:50])].count('\n') + 1
        print(f"IMBALANCE at JS line {line_idx+1} (HTML line ~{html_line}): brace={brace} paren={paren} bracket={bracket}")
        print(f"  Line: {line.strip()[:120]}")
        # Reset to 0 to continue finding more issues
        brace = max(brace, 0)
        paren = max(paren, 0)
        bracket = max(bracket, 0)

print(f"\nFinal balance: brace={brace} paren={paren} bracket={bracket}")
if brace != 0:
    print(f"  -> {abs(brace)} unclosed braces" if brace > 0 else f"  -> {abs(brace)} extra closing braces")
if paren != 0:
    print(f"  -> {abs(paren)} unclosed parens" if paren > 0 else f"  -> {abs(paren)} extra closing parens")
if bracket != 0:
    print(f"  -> {abs(bracket)} unclosed brackets" if bracket > 0 else f"  -> {abs(bracket)} extra closing brackets")

# Also check with node
print("\n--- Node.js syntax check ---")
import subprocess, tempfile, os
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
    tmp.write(js)
    tmp_path = tmp.name

result = subprocess.run(['node', '--check', tmp_path], capture_output=True, text=True)
if result.returncode == 0:
    print("Node.js: No syntax errors!")
else:
    print(f"Node.js ERROR: {result.stderr.strip()}")
os.unlink(tmp_path)
