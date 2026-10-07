"""PDF text extractor for Type0/Identity-H PDFs with inline resource dicts.

Uses a real content-stream tokenizer, applies ToUnicode CMaps per font, and
groups text runs into lines using their text-space coordinates.
"""
import re
import sys
import zlib
from collections import defaultdict

SRC, OUT = sys.argv[1], sys.argv[2]
raw = open(SRC, "rb").read()

# ---------------------------------------------------------------- object table
objs = {}
for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", raw):
    num = int(m.group(1))
    start = m.end()
    end = raw.find(b"endobj", start)
    objs[num] = raw[start: end if end != -1 else len(raw)]


def split_stream(body):
    m = re.search(rb"(?<![A-Za-z0-9/])stream\r?\n", body)
    if not m:
        return body, None
    return body[: m.start()], body[m.end(): body.find(b"endstream", m.end())]


def inflate(data):
    if data is None:
        return None
    try:
        return zlib.decompress(data)
    except Exception:
        try:
            return zlib.decompressobj().decompress(data)
        except Exception:
            return None


def stream_of(num):
    if num not in objs:
        return None
    return inflate(split_stream(objs[num])[1])


def head_of(num):
    return split_stream(objs[num])[0] if num in objs else b""


def balance_dict(text, start):
    """Return the balanced <<...>> substring beginning at/after `start`."""
    i = text.find(b"<<", start)
    if i < 0:
        return None
    depth, j = 0, i
    while j < len(text) - 1:
        pair = text[j: j + 2]
        if pair == b"<<":
            depth += 1
            j += 2
            continue
        if pair == b">>":
            depth -= 1
            j += 2
            if depth == 0:
                return text[i:j]
            continue
        j += 1
    return None


# ---------------------------------------------------------------- ToUnicode
def hex2text(h):
    if not h:
        return ""
    if len(h) % 4:
        h = h.ljust((len(h) // 4 + 1) * 4, "0")
    out = []
    i = 0
    while i < len(h):
        cp = int(h[i: i + 4], 16)
        if 0xD800 <= cp <= 0xDBFF and i + 8 <= len(h):
            lo = int(h[i + 4: i + 8], 16)
            if 0xDC00 <= lo <= 0xDFFF:
                out.append(chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)))
                i += 8
                continue
        if cp:
            out.append(chr(cp))
        i += 4
    return "".join(out)


def parse_cmap(data):
    text = data.decode("latin-1", "replace")
    cmap = {}
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
            cmap[int(src, 16)] = hex2text(dst)
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, arr in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S
        ):
            for i, dst in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", arr)):
                cmap[int(lo, 16) + i] = hex2text(dst)
        stripped = re.sub(r"<[0-9A-Fa-f]+>\s*<[0-9A-Fa-f]+>\s*\[.*?\]", " ", blk, flags=re.S)
        for lo, hi, dst in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", stripped
        ):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            base = int(dst, 16)
            for k in range(hi_i - lo_i + 1):
                cmap[lo_i + k] = hex2text("%04X" % (base + k))
    return cmap


font_cmap_cache = {}
DEBUG = {"tf": 0, "tf_mapped": 0, "show": 0, "hex": 0}


def cmap_for_font(fnum):
    if fnum in font_cmap_cache:
        return font_cmap_cache[fnum]
    cm = None
    m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", head_of(fnum))
    if m:
        data = stream_of(int(m.group(1)))
        if data:
            cm = parse_cmap(data)
    font_cmap_cache[fnum] = cm
    return cm


# ---------------------------------------------------------------- page order
def page_tree_order():
    root = None
    for num in objs:
        h = head_of(num)
        if re.search(rb"/Type\s*/Pages", h) and b"/Parent" not in h:
            root = num
            break
    if root is None:
        for num in objs:
            if re.search(rb"/Type\s*/Pages", head_of(num)):
                root = num
                break
    order = []

    def walk(n):
        h = head_of(n)
        kids = re.search(rb"/Kids\s*\[(.*?)\]", h, re.S)
        if not kids:
            order.append(n)
            return
        for k in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1)):
            walk(int(k))

    if root is not None:
        walk(root)
    return order


pages = page_tree_order()
if not pages:
    pages = sorted(
        n for n in objs if re.search(rb"/Type\s*/Page[^s]", head_of(n))
    )


# ---------------------------------------------------------------- tokenizer
TOKEN_RE = re.compile(
    rb"""
    (?P<dictOpen><<) | (?P<dictClose>>>) |
    (?P<arrOpen>\[) | (?P<arrClose>\]) |
    (?P<hex><[0-9A-Fa-f\s]*>) |
    (?P<name>/[^\s/\[\]<>(){}]*) |
    (?P<num>[+-]?(?:\d+\.?\d*|\.\d+)) |
    (?P<str>\((?:\\.|[^\\()])*\)) |
    (?P<op>[A-Za-z'"*][A-Za-z0-9'"*]*)
    """,
    re.X | re.S,
)


def tokenize(data):
    for m in TOKEN_RE.finditer(data):
        kind = m.lastgroup
        tok = m.group()
        if kind in ("dictOpen", "dictClose", "arrOpen", "arrClose"):
            yield kind, tok
        elif kind == "hex":
            yield "hex", re.sub(rb"\s+", b"", tok[1:-1])
        elif kind == "name":
            yield "name", tok[1:]
        elif kind == "num":
            yield "num", float(tok)
        elif kind == "str":
            yield "str", tok[1:-1]
        elif kind == "op":
            yield "op", tok
        else:
            yield kind, tok


def decode_hex(h, cmap):
    h = h.decode("ascii", "replace")
    if not h:
        return ""
    if cmap is None:
        try:
            return bytes.fromhex(h).decode("latin-1")
        except Exception:
            return ""
    out = []
    for i in range(0, len(h) - 1, 4):
        out.append(cmap.get(int(h[i: i + 4], 16), ""))
    return "".join(out)


def decode_str(s, cmap):
    if cmap is None:
        return s.decode("latin-1", "replace")
    out = []
    for i in range(0, len(s) - 1, 2):
        out.append(cmap.get((s[i] << 8) | s[i + 1], ""))
    return "".join(out)


# ---------------------------------------------------------------- extraction
def extract_page(pid):
    h = head_of(pid)
    res = balance_dict(h, h.find(b"/Resources")) or h
    # font name -> object number
    fonts = {}
    fd = balance_dict(res, res.find(b"/Font"))
    if fd:
        for name, onum in re.findall(rb"/([^\s/\[\]<>(){}]+)\s+(\d+)\s+\d+\s+R", fd):
            fonts[b"/" + name] = int(onum)

    contents = []
    cm = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", h)
    if cm:
        contents.append(int(cm.group(1)))
    else:
        cm = re.search(rb"/Contents\s*\[(.*?)\]", h, re.S)
        if cm:
            contents += [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(1))]

    items = []
    for cid in contents:
        data = stream_of(cid)
        if not data:
            continue
        cur = None
        cmap = None
        tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        tlm = list(tm)
        stack = []
        lead = 0.0
        pending = []

        def flush():
            if pending:
                items.append((round(tm[5], 1), round(tm[4], 1), "".join(pending)))
                pending.clear()

        for kind, val in tokenize(data):
            if kind == "op":
                op = val
                if op == b"BT":
                    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                    tlm = list(tm)
                elif op == b"Tf" and len(stack) >= 2:
                    fent = stack[-2]
                    if isinstance(fent, tuple) and fent[0] == "name":
                        cur = b"/" + fent[1]
                        cmap = cmap_for_font(fonts.get(cur, -1))
                        DEBUG["tf"] += 1
                        if cmap:
                            DEBUG["tf_mapped"] += 1
                elif op == b"Tm" and len(stack) >= 6:
                    flush()
                    tm = [float(x) for x in stack[-6:]]
                    tlm = list(tm)
                elif op in (b"Td", b"TD") and len(stack) >= 2:
                    flush()
                    if op == b"TD":
                        lead = -float(stack[-1])
                    tlm[4] += float(stack[-2])
                    tlm[5] += float(stack[-1])
                    tm = list(tlm)
                elif op == b"TL" and stack:
                    lead = float(stack[-1])
                elif op == b"T*":
                    flush()
                    tlm[5] -= lead
                    tm = list(tlm)
                elif op == b"Tj" and stack and stack[-1] is not None:
                    pending.append(interpret_show(stack[-1], cmap))
                elif op == b"TJ" and stack:
                    pending.append(interpret_tj(stack[-1], cmap))
                elif op == b"'":
                    flush()
                    tlm[5] -= lead
                    tm = list(tlm)
                    if stack:
                        pending.append(interpret_show(stack[-1], cmap))
                elif op == b'"':
                    flush()
                    tlm[5] -= lead
                    tm = list(tlm)
                    if stack:
                        pending.append(interpret_show(stack[-1], cmap))
                elif op == b"ET":
                    flush()
                stack = []
            elif kind == "num":
                stack.append(val)
            elif kind == "hex":
                stack.append(("hex", val))
            elif kind == "str":
                stack.append(("str", val))
            elif kind == "name":
                stack.append(("name", val))
            elif kind in ("dictOpen", "arrOpen"):
                stack.append(None)
            elif kind in ("dictClose", "arrClose"):
                if stack:
                    stack.pop()
        flush()
    return items


def interpret_show(v, cmap):
    DEBUG["show"] += 1
    if isinstance(v, tuple) and len(v) == 2:
        if v[0] == "hex":
            DEBUG["hex"] += 1
            return decode_hex(v[1], cmap)
        return decode_str(v[1], cmap)
    return ""


def interpret_tj(arr, cmap):
    if not isinstance(arr, list):
        return ""
    out = []
    for el in arr:
        if isinstance(el, tuple) and len(el) == 2:
            if el[0] == "hex":
                out.append(decode_hex(el[1], cmap))
            else:
                out.append(decode_str(el[1], cmap))
        elif isinstance(el, float):
            if el < -180:
                out.append(" ")
    return "".join(out)


# ---------------------------------------------------------------- assemble
out_lines = []
for pno, pid in enumerate(pages, 1):
    items = extract_page(pid)
    lines = defaultdict(list)
    for y, x, s in items:
        lines[y].append((x, s))
    out_lines.append("\n===== PAGE %d =====\n" % pno)
    for y in sorted(lines):
        parts = [s for _, s in sorted(lines[y])]
        line = "".join(parts).strip()
        if line:
            out_lines.append(line)

text = "\n".join(out_lines).replace("\x00", "")
open(OUT, "w", encoding="utf-8", newline="\n").write(text)
print("pages:", len(pages), "chars:", len(text), "nul:", text.count("\x00"))
print("cmaps loaded:", sum(1 for v in font_cmap_cache.values() if v))
print("debug:", DEBUG)
