"""极简 PDF 文本提取器（内置，无第三方依赖）。

用于知识库导入 PDF 时抽取文字：FlateDecode 解压 + Type0/Identity-H
字体的 ToUnicode CMap 映射。复杂版式（表格、扫描件）仍建议接入
PDF 2.2 指定的 DeepDOC + PaddleOCR。
"""

from __future__ import annotations

import re
import zlib
from collections import defaultdict

# ---------------------------------------------------------------- 对象解析


def _objects(raw: bytes) -> dict[int, bytes]:
    objs: dict[int, bytes] = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", raw):
        num = int(m.group(1))
        start = m.end()
        end = raw.find(b"endobj", start)
        objs[num] = raw[start: end if end != -1 else len(raw)]
    return objs


def _split_stream(body: bytes) -> tuple[bytes, bytes | None]:
    m = re.search(rb"(?<![A-Za-z0-9/])stream\r?\n", body)
    if not m:
        return body, None
    return body[: m.start()], body[m.end(): body.find(b"endstream", m.end())]


def _inflate(data: bytes | None) -> bytes | None:
    if data is None:
        return None
    try:
        return zlib.decompress(data)
    except Exception:
        try:
            return zlib.decompressobj().decompress(data)
        except Exception:
            return None


def _head(objs: dict[int, bytes], num: int) -> bytes:
    return _split_stream(objs[num])[0] if num in objs else b""


def _stream(objs: dict[int, bytes], num: int) -> bytes | None:
    if num not in objs:
        return None
    return _inflate(_split_stream(objs[num])[1])


def _balance(text: bytes, start: int) -> bytes | None:
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


# ---------------------------------------------------------------- CMap


def _hex_to_text(h: str) -> str:
    if not h:
        return ""
    if len(h) % 4:
        h = h.ljust((len(h) // 4 + 1) * 4, "0")
    out: list[str] = []
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


def _parse_cmap(data: bytes) -> dict[int, str]:
    text = data.decode("latin-1", "replace")
    cmap: dict[int, str] = {}
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
            cmap[int(src, 16)] = _hex_to_text(dst)
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, arr in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", blk, re.S
        ):
            for i, dst in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", arr)):
                cmap[int(lo, 16) + i] = _hex_to_text(dst)
        stripped = re.sub(
            r"<[0-9A-Fa-f]+>\s*<[0-9A-Fa-f]+>\s*\[.*?\]", " ", blk, flags=re.S
        )
        for lo, hi, dst in re.findall(
            r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", stripped
        ):
            lo_i, hi_i, base = int(lo, 16), int(hi, 16), int(dst, 16)
            for k in range(hi_i - lo_i + 1):
                cmap[lo_i + k] = _hex_to_text("%04X" % (base + k))
    return cmap


# ---------------------------------------------------------------- 内容流


_TOKEN_RE = re.compile(
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


def _tokenize(data: bytes):
    for m in _TOKEN_RE.finditer(data):
        kind = m.lastgroup
        tok = m.group()
        if kind == "hex":
            yield "hex", re.sub(rb"\s+", b"", tok[1:-1])
        elif kind == "name":
            yield "name", tok[1:]
        elif kind == "num":
            yield "num", float(tok)
        elif kind == "str":
            yield "str", tok[1:-1]
        else:
            yield kind, tok


def _decode_hex(h: bytes, cmap: dict[int, str] | None) -> str:
    text = h.decode("ascii", "replace")
    if not text:
        return ""
    if cmap is None:
        try:
            return bytes.fromhex(text).decode("latin-1")
        except Exception:
            return ""
    return "".join(
        cmap.get(int(text[i: i + 4], 16), "") for i in range(0, len(text) - 1, 4)
    )


def _decode_str(s: bytes, cmap: dict[int, str] | None) -> str:
    if cmap is None:
        return s.decode("latin-1", "replace")
    return "".join(cmap.get((s[i] << 8) | s[i + 1], "") for i in range(0, len(s) - 1, 2))


def _page_order(objs: dict[int, bytes]) -> list[int]:
    root = None
    for num in objs:
        h = _head(objs, num)
        if re.search(rb"/Type\s*/Pages", h) and b"/Parent" not in h:
            root = num
            break
    if root is None:
        for num in objs:
            if re.search(rb"/Type\s*/Pages", _head(objs, num)):
                root = num
                break
    order: list[int] = []

    def walk(n: int) -> None:
        h = _head(objs, n)
        kids = re.search(rb"/Kids\s*\[(.*?)\]", h, re.S)
        if not kids:
            order.append(n)
            return
        for k in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1)):
            walk(int(k))

    if root is not None:
        walk(root)
    if not order:
        order = sorted(
            n for n in objs if re.search(rb"/Type\s*/Page[^s]", _head(objs, n))
        )
    return order


def _extract_page(objs: dict[int, bytes], pid: int) -> list[tuple[float, float, str]]:
    h = _head(objs, pid)
    res = _balance(h, h.find(b"/Resources")) or h
    fonts: dict[bytes, int] = {}
    fd = _balance(res, res.find(b"/Font"))
    if fd:
        for name, onum in re.findall(rb"/([^\s/\[\]<>(){}]+)\s+(\d+)\s+\d+\s+R", fd):
            fonts[b"/" + name] = int(onum)

    cmap_cache: dict[int, dict[int, str] | None] = {}

    def cmap_for(fnum: int) -> dict[int, str] | None:
        if fnum in cmap_cache:
            return cmap_cache[fnum]
        cm = None
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", _head(objs, fnum))
        if m:
            data = _stream(objs, int(m.group(1)))
            if data:
                cm = _parse_cmap(data)
        cmap_cache[fnum] = cm
        return cm

    contents: list[int] = []
    cm = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", h)
    if cm:
        contents.append(int(cm.group(1)))
    else:
        cm = re.search(rb"/Contents\s*\[(.*?)\]", h, re.S)
        if cm:
            contents += [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(1))]

    items: list[tuple[float, float, str]] = []
    for cid in contents:
        data = _stream(objs, cid)
        if not data:
            continue
        tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        tlm = list(tm)
        stack: list = []
        lead = 0.0
        pending: list[str] = []
        cmap: dict[int, str] | None = None

        def flush() -> None:
            if pending:
                items.append((round(tm[5], 1), round(tm[4], 1), "".join(pending)))
                pending.clear()

        for kind, val in _tokenize(data):
            if kind == "op":
                op = val
                if op == b"BT":
                    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                    tlm = list(tm)
                elif op == b"Tf" and len(stack) >= 2:
                    fent = stack[-2]
                    if isinstance(fent, tuple) and fent[0] == "name":
                        cmap = cmap_for(fonts.get(b"/" + fent[1], -1))
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
                elif op == b"Tj" and stack:
                    v = stack[-1]
                    if isinstance(v, tuple):
                        pending.append(
                            _decode_hex(v[1], cmap) if v[0] == "hex" else _decode_str(v[1], cmap)
                        )
                elif op == b"TJ" and stack and isinstance(stack[-1], list):
                    for el in stack[-1]:
                        if isinstance(el, tuple):
                            pending.append(
                                _decode_hex(el[1], cmap)
                                if el[0] == "hex"
                                else _decode_str(el[1], cmap)
                            )
                        elif isinstance(el, float) and el < -180:
                            pending.append(" ")
                elif op in (b"'", b'"'):
                    flush()
                    tlm[5] -= lead
                    tm = list(tlm)
                    if stack and isinstance(stack[-1], tuple):
                        v = stack[-1]
                        pending.append(
                            _decode_hex(v[1], cmap) if v[0] == "hex" else _decode_str(v[1], cmap)
                        )
                elif op == b"ET":
                    flush()
                stack = []
            elif kind == "num":
                stack.append(val)
            elif kind in ("hex", "str", "name"):
                stack.append((kind, val))
            elif kind in ("dictOpen", "arrOpen"):
                stack.append(None)
            elif kind in ("dictClose", "arrClose"):
                if stack:
                    stack.pop()
        flush()
    return items


def extract_pdf_text(raw: bytes, max_pages: int = 200) -> str:
    """从 PDF 字节流中提取文本，按行重组。"""
    objs = _objects(raw)
    pages = _page_order(objs)[:max_pages]
    out: list[str] = []
    for pno, pid in enumerate(pages, 1):
        items = _extract_page(objs, pid)
        lines: dict[float, list[tuple[float, str]]] = defaultdict(list)
        for y, x, s in items:
            lines[y].append((x, s))
        out.append(f"\n===== 第 {pno} 页 =====")
        for y in sorted(lines):
            line = "".join(s for _, s in sorted(lines[y])).strip()
            if line:
                out.append(line)
    return "\n".join(out).replace("\x00", "")


def extract_pdf_file(path: str) -> str:
    with open(path, "rb") as fh:
        return extract_pdf_text(fh.read())
