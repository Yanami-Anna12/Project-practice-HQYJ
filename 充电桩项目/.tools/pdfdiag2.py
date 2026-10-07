import re
import sys
import zlib

raw = open(sys.argv[1], "rb").read()
objs = {}
for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", raw):
    num = int(m.group(1))
    start = m.end()
    end = raw.find(b"endobj", start)
    objs[num] = raw[start:end if end != -1 else len(raw)]


def head_of(b):
    i = b.find(b"stream")
    return b[:i] if i != -1 else b


def inflate(d):
    try:
        return zlib.decompress(d)
    except Exception:
        return None


print("=== objects with /Type /Page ===")
for n, b in sorted(objs.items()):
    h = head_of(b)
    if re.search(rb"/Type\s*/Page[^s]", h):
        print(n, h[:400])
        print("---")

print()
print("=== Type0 fonts ===")
for n, b in sorted(objs.items()):
    h = head_of(b)
    if b"/Type0" in h:
        print(n, h[:400])
        print("---")

print()
print("=== objects containing /ToUnicode ===")
for n, b in sorted(objs.items()):
    h = head_of(b)
    if b"/ToUnicode" in h:
        print(n, h[:300])
        print("---")

print()
print("=== Pages tree ===")
for n, b in sorted(objs.items()):
    h = head_of(b)
    if b"/Type /Pages" in h or b"/Type/Pages" in h:
        print(n, h[:600])
        print("---")

print()
print("=== object sizes (first 40) ===")
for n in sorted(objs)[:40]:
    print(n, len(objs[n]), head_of(objs[n])[:120])
