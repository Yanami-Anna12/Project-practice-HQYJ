"""Diagnose a PDF: version, page tree, fonts, encodings, filters."""
import re
import sys
import zlib
from collections import Counter, OrderedDict

path = sys.argv[1]
raw = open(path, "rb").read()
print("size", len(raw))
print("header", raw[:16])

# Collect indirect objects by scanning "N G obj ... endobj"
objs = {}
for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", raw):
    num = int(m.group(1))
    start = m.end()
    end = raw.find(b"endobj", start)
    if end == -1:
        end = len(raw)
    objs[num] = raw[start:end]

print("objects", len(objs))

# Object streams (compressed xref) hold dicts too
objstm_nums = [n for n, b in objs.items() if b"/ObjStm" in b[:400]]
print("objstm count", len(objstm_nums))

def inflate(data):
    try:
        return zlib.decompress(data)
    except Exception:
        try:
            d = zlib.decompressobj()
            return d.decompress(data)
        except Exception:
            return None

def streams_of(body):
    out = []
    for m in re.finditer(rb"stream\r?\n", body):
        s = m.end()
        e = body.find(b"endstream", s)
        if e == -1:
            continue
        out.append(body[s:e])
    return out

# Expand object streams into synthetic objects so /Type /Page etc. become visible
expanded = dict(objs)
for n in objstm_nums:
    body = objs[n]
    for s in streams_of(body):
        dec = inflate(s)
        if not dec:
            continue
        hm = re.search(rb"/N\s+(\d+)", body)
        fm = re.search(rb"/First\s+(\d+)", body)
        if not (hm and fm):
            continue
        N = int(hm.group(1))
        first = int(fm.group(1))
        header = dec[:first].split()
        for i in range(N):
            try:
                onum = int(header[2 * i])
                off = int(header[2 * i + 1])
            except Exception:
                break
            nxt = int(header[2 * i + 3]) if 2 * i + 3 < len(header) else len(dec) - first
            expanded[onum] = dec[first + off: first + nxt]

allblob = b"\n".join(expanded.values())

print("Filters:", Counter(re.findall(rb"/Filter\s*/(\w+)", allblob)).most_common())
print("Font subtypes:", Counter(re.findall(rb"/Subtype\s*/(\w+)", allblob)).most_common(12))
print("Encoding names:", Counter(re.findall(rb"/Encoding\s*/([\w\-]+)", allblob)).most_common())
print("ToUnicode refs:", len(re.findall(rb"/ToUnicode", allblob)))
print("FontFile:", len(re.findall(rb"/FontFile\d?", allblob)))
print("Pages:", len(re.findall(rb"/Type\s*/Page[^s]", allblob)))
print("XObject Form:", len(re.findall(rb"/Subtype\s*/Form", allblob)))

# Try inflating all streams; report how many decode and sample decoded text ops
ok = 0
tot = 0
sample = None
for n, body in expanded.items():
    for s in streams_of(body):
        tot += 1
        dec = inflate(s)
        if dec is not None:
            ok += 1
            if sample is None and (b"Tj" in dec or b"TJ" in dec):
                sample = (n, dec)
print("streams", tot, "inflated", ok)
if sample:
    n, dec = sample
    print("--- sample stream obj", n, "len", len(dec))
    print(dec[:1500])
