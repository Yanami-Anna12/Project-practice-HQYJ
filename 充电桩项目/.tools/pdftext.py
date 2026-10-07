"""Minimal PDF text extractor: FlateDecode + Type0/Identity-H + ToUnicode CMaps.

Produces a reading-order text dump using Tm/Td coordinates to group lines.
"""
import re
import sys
import zlib
from collections import defaultdict

SRC = sys.argv[1]
OUT = sys.argv[2]

raw = open(SRC, "rb").read()

objs = {}
for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", raw):
    num = int(m.group(1))
    start = m.end()
    end = raw.find(b"endobj", start)
    objs[num] = raw[start:end if end != -1 else len(raw)]


def inflate(data):
    try:
        return zlib.decompress(data)
    except Exception:
        return None


def body_and_stream(body):
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return body, None
    s = m.end()
    e = body.find(b"endstream", s)
    return body[: m.start()], body[s:e]


def decode_stream(body):
    _, s = body_and_stream(body)
    if s is None:
        return None
    return inflate(s)


# ---- ToUnicode CMap parsing -------------------------------------------------
def parse_cmap(data):
    cmap = {}
    text = data.decode("latin-1", "replace")
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
            cmap[int(src, 16)] = hexstr_to_text(dst)
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        # <lo> <hi> <dstStart>
        for lo, hi, dst in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk
        ):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            base = int(dst, 16)
            width = max(1, len(dst) // 4)
            for k in range(hi_i - lo_i + 1):
                cmap[lo_i + k] = hexstr_to_text(
                    "%0*X" % (width * 4, base + k)
                )
        # <lo> <hi> [ <d1> <d2> ... ]
        for lo, hi, arr in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S
        ):
            items = re.findall(r"<([0-9A-Fa-f]*)>", arr)
            for i, dst in enumerate(items):
                cmap[int(lo, 16) + i] = hexstr_to_text(dst)
    return cmap


def hexstr_to_text(h):
    if not h:
        return ""
    if len(h) % 4:
        h = h.ljust((len(h) // 4 + 1) * 4, "0")
    out = []
    for i in range(0, len(h), 4):
        cp = int(h[i : i + 4], 16)
        if cp in (0x0000,):
            continue
        # surrogate pair
        if 0xD800 <= cp <= 0xDBFF and i + 8 <= len(h):
            lo = int(h[i + 4 : i + 8], 16)
            if 0xDC00 <= lo <= 0xDFFF:
                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                out.append(chr(cp))
                continue
        out.append(chr(cp))
    return "".join(out)


# ---- Font resource map: /F4 -> cmap ----------------------------------------
font_cmaps = {}
for num, body in objs.items():
    head, _ = body_and_stream(body)
    if b"/Type0" not in head and b"/ToUnicode" not in head:
        continue
    m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", head)
    if not m:
        continue
    tgt = int(m.group(1))
    if tgt in objs:
        dec = decode_stream(objs[tgt])
        if dec:
            font_cmaps[num] = parse_cmap(dec)

# Map resource names (/F4) to font object ids per page
page_fonts = {}


def resolve_resources(head):
    m = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", head)
    if not m:
        return None
    rid = int(m.group(1))
    if rid not in objs:
        return None
    rbody, _ = body_and_stream(objs[rid])
    return rbody


def font_map_from_resources(res):
    out = {}
    if res is None:
        return out
    fm = re.search(rb"/Font\s*<<(.*?)>>", res, re.S)
    if not fm:
        m = re.search(rb"/Font\s+(\d+)\s+\d+\s+R", res)
        if m and int(m.group(1)) in objs:
            fbody, _ = body_and_stream(objs[int(m.group(1))])
            fm = re.match(rb"\s*<<(.*)>>", fbody, re.S)
    if not fm:
        return out
    for name, onum in re.findall(rb"/(\w+)\s+(\d+)\s+\d+\s+R", fm.group(1)):
        out[b"/" + name] = int(onum)
    return out


# ---- Page order -------------------------------------------------------------
pages = []
for num, body in objs.items():
    head, _ = body_and_stream(body)
    if re.search(rb"/Type\s*/Page[^s]", head):
        pages.append(num)
pages.sort()

# Prefer /Kids order from the page tree when available
for num, body in objs.items():
    head, _ = body_and_stream(body)
    if re.search(rb"/Type\s*/Pages", head) and b"/Kids" in head:
        kids = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", head)]
        ordered = [k for k in kids if k in pages]
        if len(ordered) == len(pages) and ordered:
            pages = ordered
        break


def text_from_ops(dec, fonts, cmaps):
    """Walk content stream, tracking text matrix to group lines."""
    toks = re.findall(
        rb"/(\w+)\s+[\d.]+\s+Tf|"
        rb"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+Tm|"
        rb"([-\d.]+)\s+([-\d.]+)\s+(?:Td|TD)|"
        rb"<([0-9A-Fa-f\s]*)>\s*Tj|"
        rb"\[(.*?)\]\s*TJ|"
        rb"\((.*?)\)\s*Tj",
        dec,
        re.S,
    )
    items = []  # (y, x, text)
    cur_font = None
    x = y = 0.0
    for t in toks:
        if t[0]:
            cur_font = b"/" + t[0]
        elif t[1]:
            x = float(t[5])
            y = float(t[6])
        elif t[7]:
            x += float(t[7])
            y += float(t[8])
        elif t[9] is not None and t[9] != b"":
            s = decode_hex_text(t[9], cur_font, fonts, cmaps)
            if s:
                items.append((round(y, 1), x, s))
        elif t[10] is not None and t[10] != b"":
            s = decode_tj_array(t[10], cur_font, fonts, cmaps)
            if s:
                items.append((round(y, 1), x, s))
        elif t[11] is not None and t[11] != b"":
            s = t[11].decode("latin-1", "replace")
            if s:
                items.append((round(y, 1), x, s))
    return items


def decode_hex_text(rawhex, font, fonts, cmaps):
    h = re.sub(rb"\s+", b"", rawhex).decode("ascii", "replace")
    if not h:
        return ""
    cid_src = h
    # ASCII fallback for simple fonts
    if bytes(font) not in cmaps and (len(h) % 4 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", h)):
        # Try 2-byte CIDs against the page font first
        pass
    cmap = cmaps.get(font)
    if cmap is None:
        try:
            return bytes.fromhex(h).decode("latin-1")
        except Exception:
            return ""
    out = []
    for i in range(0, len(h) - 1, 4):
        cid = int(h[i : i + 4], 16)
        out.append(cmap.get(cid, ""))
    return "".join(out)


def decode_tj_array(raw, font, fonts, cmaps):
    out = []
    for m in re.finditer(rb"<([0-9A-Fa-f\s]*)>|\((.*?)\)|([-\d.]+)", raw, re.S):
        if m.group(1) is not None:
            out.append(decode_hex_text(m.group(1), font, fonts, cmaps))
        elif m.group(2) is not None:
            out.append(m.group(2).decode("latin-1", "replace"))
        else:
            v = float(m.group(3))
            if v < -180:
                out.append(" ")
    return "".join(out)


# ---- Extract -----------------------------------------------------------------
result = []
for pno, pid in enumerate(pages, 1):
    head, _ = body_and_stream(objs[pid])
    res = resolve_resources(head)
    fonts = font_map_from_resources(res)
    cmaps = {k: font_cmaps.get(v) for k, v in fonts.items()}
    # content stream refs
    contents = []
    cm = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", head)
    if cm and int(cm.group(1)) in objs:
        contents.append(int(cm.group(1)))
    else:
        cm = re.search(rb"/Contents\s*\[(.*?)\]", head, re.S)
        if cm:
            contents += [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(1))]
    items = []
    for cid in contents:
        dec = decode_stream(objs[cid])
        if dec:
            items += text_from_ops(dec, fonts, cmaps)
    # group by rounded y
    lines = defaultdict(list)
    for y, x, s in items:
        lines[y].append((x, s))
    result.append("\n===== PAGE %d =====\n" % pno)
    for y in sorted(lines):
        parts = [s for _, s in sorted(lines[y])]
        line = "".join(parts).strip()
        if line:
            result.append(line)

out = "\n".join(result)
open(OUT, "w", encoding="utf-8").write(out)
print("wrote", OUT, len(out), "chars;", len(pages), "pages")
