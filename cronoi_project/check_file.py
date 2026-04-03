with open(r'C:\PROJECTS\cronoi_project\cronoi_project\frontend\Cronoi_LS_v2.html', 'rb') as f:
    data = f.read()

# Check for null bytes
null_positions = [i for i, b in enumerate(data) if b == 0]
if null_positions:
    print(f'NULL BYTES FOUND: {len(null_positions)} occurrences')
    for pos in null_positions[:10]:
        ctx = data[max(0,pos-20):pos+20]
        print(f'  at byte {pos}: ...{ctx!r}...')
else:
    print('No null bytes found')

# Check BOM
has_bom = data[:3] == b'\xef\xbb\xbf'
print(f'Starts with BOM: {has_bom}')
print(f'Total size: {len(data):,} bytes')

# Check for any control characters (except newline, carriage return, tab)
controls = [(i, data[i]) for i in range(len(data)) if data[i] < 32 and data[i] not in (9, 10, 13)]
if controls:
    print(f'Control chars found: {len(controls)}')
    for pos, byte in controls[:10]:
        print(f'  at byte {pos}: 0x{byte:02X}')
else:
    print('No unusual control characters')

# Check for inconsistent line endings
cr_count = data.count(b'\r\n')
lf_only = data.count(b'\n') - cr_count
print(f'CRLF: {cr_count}, LF-only: {lf_only}')
