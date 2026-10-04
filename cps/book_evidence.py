# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""In-book evidence for ebook metadata checks.

Reads an ebook file the way a person checks it by hand: the title page, the
copyright page, labelled ISBNs, front-matter disclaimers, length, chapter count
and language. Embedded OPF metadata and the filename are recorded as *claims*,
never as truth.

Pure stdlib, no calibre / CWA imports, no network, no writes. Deterministic for
a given file. Only EPUB is read in full; every other format returns an
``insufficient`` result instead of a guess.

Public API:
    extract(path)              -> dict  (Evidence; see EVIDENCE_KEYS)
    extract_epub(path_or_file) -> dict
    normalize_isbn(text)       -> "978..." 13-digit string or None
    find_labelled_isbns(text)  -> list of dicts
    find_disclaimers(text)     -> list of dicts
    norm_text(text)            -> lower-case, accent-free, space-joined tokens
"""

import html
import posixpath
import re
import unicodedata
import urllib.parse
import zipfile
from collections import Counter
from xml.etree import ElementTree as ET

EVIDENCE_VERSION = 2

# Reading limits: a hostile or broken file must not exhaust memory.
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
FRONT_CHARS = 20000          # front matter window (title page, dedication, copyright when at the front)
COPYRIGHT_WINDOW = 1500      # chars kept either side of a copyright marker found anywhere in the book
MAX_COPYRIGHT_BLOCKS = 4
SUMMARY_WORD_CEILING = 25000  # a disclaimer only counts when the whole file is shorter than this

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}

EVIDENCE_KEYS = (
    "status", "reason", "format", "claims", "isbns_in_text", "disclaimers", "words", "chapters",
    "spine_docs", "language", "english_ratio", "front_norm", "copyright_norm", "doc_title",
    "summary_file", "publisher_lines", "name_hits", "drm",
)


# ---------------------------------------------------------------- text helpers

def norm_text(text):
    """Lower-case, strip accents and apostrophes, '&' -> 'and', return space-joined word tokens."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", html.unescape(str(text)))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold().replace("&", " and ")
    s = re.sub(r"['’‘`ʼ]", "", s)       # ancestor's -> ancestors
    return " ".join(re.findall(r"[^\W_]+", s))


_BLOCK_TAGS = re.compile(r"(?i)</?(p|div|h[1-6]|br|li|tr|section|blockquote|title)\b[^>]*>")


def html_to_text(raw):
    """Visible text of an (X)HTML document. Regex based: fast and good enough for word counts and phrase checks."""
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    s = re.sub(r"(?is)<(script|style|head)\b[^>]*>.*?</\1>", " ", s)
    s = _BLOCK_TAGS.sub("\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def head_title(raw):
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", s)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


# ---------------------------------------------------------------- ISBNs

def _isbn10_ok(d):
    if len(d) != 10 or not d[:9].isdigit() or not (d[9].isdigit() or d[9] == "X"):
        return False
    return sum((10 - i) * (10 if ch == "X" else int(ch)) for i, ch in enumerate(d)) % 11 == 0


def _isbn13_ok(d):
    if len(d) != 13 or not d.isdigit() or d[:3] not in ("978", "979"):
        return False
    return sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(d)) % 10 == 0


def isbn10_to_13(d):
    core = "978" + d[:9]
    total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(core))
    return core + str((10 - total % 10) % 10)


def _degenerate(d13):
    # 0000000000 -> 9780000000002 passes the checksum; so does any all-same body. Not a real ISBN.
    body = d13[3:12]
    return len(set(body)) <= 1


def normalize_isbn(text):
    """Return the 13-digit form of a checksum-valid ISBN-10/13, else None."""
    if not text:
        return None
    d = re.sub(r"[^0-9Xx]", "", str(text)).upper()
    if len(d) == 10 and _isbn10_ok(d):
        d13 = isbn10_to_13(d)
    elif len(d) == 13 and _isbn13_ok(d):
        d13 = d
    else:
        return None
    return None if _degenerate(d13) else d13


_SEP = r"[\s\-‐-―.]"
_ISBN_LABELLED = re.compile(
    r"ISBN(?:[\s\-]?1[03])?"
    # an edition note between label and number: "ISBN (hardcover) 978-...", "ISBN [ebook]: 978-..."
    r"(?P<note>\s*[\(\[][A-Za-z][A-Za-z .,/-]{0,28}[\)\]])?"
    r"(?P<gap>[^0-9A-Za-z]{0,25}?)"
    r"(?P<num>97[89]" + _SEP + r"?(?:[0-9]" + _SEP + r"?){9}[0-9]|(?:[0-9]" + _SEP + r"?){9}[0-9Xx])(?![0-9])",
    re.I,
)
_KIND_WORDS = (
    ("ebook", re.compile(r"e-?book|e-?isbn|epub|electronic|digital|kindle|e-?edition", re.I)),
    ("print", re.compile(r"hardcover|hardback|paperback|print|trade|cloth|pbk|hbk", re.I)),
    ("audio", re.compile(r"audio", re.I)),
)


def _looks_like_key_line(raw):
    # Printer's key "10 9 8 7 6 5 4 3 2 1" / "15 16 17 18 19": many 1-2 digit groups split by spaces.
    groups = re.split(r"\s+", raw.strip())
    return len(groups) >= 5 and sum(1 for g in groups if len(re.sub(r"\D", "", g)) <= 2) >= 5


def find_labelled_isbns(text):
    """ISBNs printed next to an 'ISBN' label, checksum-valid, with a coarse kind (ebook/print/audio/unknown).

    Unlabelled digit runs are ignored on purpose: a printer's key line passes the checksum.
    """
    out, seen = [], set()
    for m in _ISBN_LABELLED.finditer(text or ""):
        raw = m.group("num")
        if _looks_like_key_line(raw):
            continue
        d13 = normalize_isbn(raw)
        if not d13 or d13 in seen:
            continue
        seen.add(d13)
        # Kind from the closest text first: the label itself and its note, then the label's own
        # line, then a window either side. A wide window alone tagged "Hardcover ISBN ..." as an
        # ebook when "eBook ISBN ..." was printed on the next line.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        before = text[max(line_start, m.start() - 25): m.start()]
        kind = "unknown"
        for ctx in (before + m.group(0), line, text[max(0, m.start() - 40): m.end() + 30]):
            for name, rx in _KIND_WORDS:
                if rx.search(ctx):
                    kind = name
                    break
            if kind != "unknown":
                break
        out.append({"isbn": d13, "raw": raw.strip(), "kind": kind, "offset": m.start()})
    return out


# ---------------------------------------------------------------- disclaimers

# Strong: phrases a real book essentially never prints in its front matter.
DISCLAIMER_STRONG = (
    r"this is not the original book", r"not the original book", r"unofficial summary",
    r"this is a summary", r"this book is a summary", r"summary (?:and|&) analysis",
    r"not affiliated with (?:the )?(?:original )?(?:author|publisher)",
    r"independent(?:ly)? (?:published )?(?:summary|analysis|companion)",
    r"is meant to be used (?:as a companion|alongside)",
)
# Weak: real books do print these (#188 "summary of the evidence", #20 "workbooks", #182 "companion to").
DISCLAIMER_WEAK = (r"summary of", r"study guide", r"workbook", r"companion to", r"analysis of", r"key takeaways")
_DIS_STRONG = re.compile("|".join(DISCLAIMER_STRONG), re.I)
_DIS_WEAK = re.compile("|".join(DISCLAIMER_WEAK), re.I)


def find_disclaimers(text, limit_chars=15000):
    t = (text or "")[:limit_chars]
    hits = [{"phrase": m.group(0).lower(), "strength": "strong", "offset": m.start()} for m in _DIS_STRONG.finditer(t)]
    hits += [{"phrase": m.group(0).lower(), "strength": "weak", "offset": m.start()} for m in _DIS_WEAK.finditer(t)]
    return sorted(hits, key=lambda h: h["offset"])


# ---------------------------------------------------------------- language

_EN_STOP = frozenset(
    "the of and to a in is that it was he for on are as with his they i at be this have from or one had by "
    "but not what all were we when your can said there an which she do their if will".split()
)


def english_ratio(text, max_tokens=5000):
    toks = re.findall(r"[a-z]+", (text or "").lower())[:max_tokens]
    return round(sum(1 for t in toks if t in _EN_STOP) / len(toks), 3) if toks else None


# ---------------------------------------------------------------- EPUB

class EvidenceError(Exception):
    pass


def _safe_xml(raw):
    head = raw[:4096] if isinstance(raw, bytes) else raw[:4096].encode()
    if b"<!ENTITY" in head or b"<!entity" in head:
        raise EvidenceError("XML declares entities; refused")
    return ET.fromstring(raw)


class _Reader:
    def __init__(self, zf):
        self.zf = zf
        self.total = 0
        self.names = set(zf.namelist())

    def read(self, name):
        info = self.zf.getinfo(name)
        if info.file_size > MAX_ENTRY_BYTES:
            raise EvidenceError("entry too large: %s" % name)
        self.total += info.file_size
        if self.total > MAX_TOTAL_BYTES:
            raise EvidenceError("book too large to inspect")
        return self.zf.read(name)


def _texts(elems):
    return [re.sub(r"\s+", " ", "".join(e.itertext())).strip() for e in elems]


def _opf_claims(opf):
    md = opf.find("opf:metadata", NS)
    if md is None:
        md = opf
    claims = {
        "title": [t for t in _texts(md.iter("{%s}title" % NS["dc"])) if t],
        "creators": [],
        "publisher": [t for t in _texts(md.iter("{%s}publisher" % NS["dc"])) if t],
        "language": [t for t in _texts(md.iter("{%s}language" % NS["dc"])) if t],
        "identifiers": [],
        "isbns": [],
        "series": None,
        "series_index": None,
    }
    for e in md.iter("{%s}creator" % NS["dc"]):
        name = re.sub(r"\s+", " ", "".join(e.itertext())).strip()
        if not name:
            continue
        role = e.get("{%s}role" % NS["opf"]) or e.get("role") or ""
        if role and role.lower() not in ("aut", ""):
            continue
        claims["creators"].append({"name": name, "file_as": e.get("{%s}file-as" % NS["opf"]) or ""})
    for e in md.iter("{%s}identifier" % NS["dc"]):
        val = "".join(e.itertext()).strip()
        scheme = e.get("{%s}scheme" % NS["opf"]) or ""
        claims["identifiers"].append({"scheme": scheme, "value": val[:120]})
        d13 = normalize_isbn(re.sub(r"(?i)^urn:isbn:", "", val))
        if d13 and (scheme.lower() == "isbn" or "isbn" in val.lower() or re.fullmatch(r"[0-9\-\sXx]{10,17}", val)):
            if d13 not in claims["isbns"]:
                claims["isbns"].append(d13)
    for e in md.iter("{%s}meta" % NS["opf"]):
        if e.get("name") == "calibre:series":
            claims["series"] = e.get("content")
        elif e.get("name") == "calibre:series_index":
            claims["series_index"] = e.get("content")
    return claims


def _chapters(reader, opf, manifest):
    # EPUB3 nav first, then NCX navPoints; spine length is the caller's fallback.
    for item in opf.iter("{%s}item" % NS["opf"]):
        if "nav" in (item.get("properties") or "").split():
            path = manifest.get(item.get("id"))
            if path and path in reader.names:
                try:
                    raw = reader.read(path).decode("utf-8", "replace")
                except EvidenceError:
                    return None
                m = re.search(r'(?is)<nav[^>]*epub:type="toc"[^>]*>(.*?)</nav>', raw)
                if m:
                    return len(re.findall(r"(?i)<li\b", m.group(1)))
    spine = opf.find("opf:spine", NS)
    toc_id = spine.get("toc") if spine is not None else None
    path = manifest.get(toc_id) if toc_id else None
    if path and path in reader.names:
        try:
            raw = reader.read(path)
            return len(re.findall(rb"<navPoint\b", raw))
        except EvidenceError:
            return None
    return None


_COPYRIGHT_MARK = re.compile(r"ISBN|©|\bcopyright\b|all rights reserved|library of congress|first published", re.I)
_COPYRIGHT_KINDS = (
    ("isbn", re.compile(r"ISBN\W{0,25}\d", re.I)),
    ("sign", re.compile(r"©|\(c\)\s*(?:19|20)\d\d|copyright\s*(?:©\s*)?(?:19|20)\d\d", re.I)),
    ("rights", re.compile(r"all rights reserved|moral right", re.I)),
    ("cip", re.compile(r"library of congress|british library|cataloging|cataloguing", re.I)),
    ("published", re.compile(r"first published|published by|published in", re.I)),
)
_PUBLISHER_LINE = re.compile(r"(?im)^(?:.{0,40}?)(?:published by|publishing group|an imprint of|imprint of|publishers?\b).{0,80}$")


def name_hits(body_norm, names):
    """For each name: is its surname (last word, 3+ letters) printed anywhere in the book text?"""
    hay = " " + body_norm + " "
    out = {}
    for n in names or ():
        toks = [t for t in norm_text(re.sub(r"\([^)]*\)", " ", n.replace("|", ","))).split() if len(t) >= 2]
        sn = toks[-1] if toks else ""
        out[n] = bool(len(sn) >= 3 and (" " + sn + " ") in hay)
    return out


def extract_epub(path_or_file, probe_names=()):
    try:
        zf = zipfile.ZipFile(path_or_file)
    except (zipfile.BadZipFile, OSError) as exc:
        return _insufficient("epub", "not a readable zip: %s" % exc)
    try:
        return _extract_epub(_Reader(zf), probe_names)
    except (EvidenceError, ET.ParseError, KeyError, UnicodeError, zipfile.BadZipFile, OSError) as exc:
        return _insufficient("epub", "%s: %s" % (type(exc).__name__, str(exc)[:120]))
    finally:
        zf.close()


# Files DRM schemes leave in META-INF, used to name the scheme in the log.
_DRM_MARKERS = (("META-INF/rights.xml", "adobe-adept"), ("META-INF/sinf.xml", "apple-fairplay"),
                ("META-INF/license.lcpl", "readium-lcp"))


def _extract_epub(reader, probe_names=()):
    container = _safe_xml(reader.read("META-INF/container.xml"))
    root = container.find(".//c:rootfile", NS)
    if root is None:
        raise EvidenceError("container.xml has no rootfile")
    opf_path = root.get("full-path")
    opf = _safe_xml(reader.read(opf_path))
    base = posixpath.dirname(opf_path)
    manifest = {}
    for item in opf.iter("{%s}item" % NS["opf"]):
        href = item.get("href")
        if href:
            manifest[item.get("id")] = posixpath.normpath(posixpath.join(base, urllib.parse.unquote(href)))
    spine = [manifest.get(r.get("idref")) for r in opf.iter("{%s}itemref" % NS["opf"])]
    spine = [p for p in spine if p and p in reader.names]
    if not spine:
        raise EvidenceError("empty spine")
    if "META-INF/encryption.xml" in reader.names:
        enc = reader.read("META-INF/encryption.xml").decode("utf-8", "replace")
        locked = {posixpath.normpath(urllib.parse.unquote(u)) for u in re.findall(r'CipherReference[^>]*URI="([^"]+)"', enc)}
        if locked & set(spine):
            # The book's text is encrypted (obfuscated fonts are never in the spine). A partly
            # encrypted book can still yield a few thousand plain words, so this is decided
            # here, before any text is read, not from the word count.
            scheme = next((name for marker, name in _DRM_MARKERS if marker in reader.names), "unknown")
            out = _insufficient("epub", "text is encrypted (DRM, %s)" % scheme)
            out.update(status="drm", drm={"scheme": scheme, "encrypted": len(locked & set(spine))})
            return out

    claims = _opf_claims(opf)
    texts, titles = [], []
    for p in spine:
        raw = reader.read(p)
        texts.append(html_to_text(raw))
        titles.append(head_title(raw))

    words = sum(len(t.split()) for t in texts)
    body = "\n".join(texts)

    # Front matter: spine documents in reading order until FRONT_CHARS of text.
    front, n = [], 0
    for t in texts:
        if n >= FRONT_CHARS:
            break
        front.append(t)
        n += len(t)
    front_text = "\n".join(front)[:FRONT_CHARS]

    # Copyright pages anywhere (#167's is at the back of the book). Rank documents by how many distinct
    # copyright markers they carry, so a contents page that merely lists "Copyright" does not win.
    scored = []
    for idx, t in enumerate(texts):
        kinds = {k for k, rx in _COPYRIGHT_KINDS if rx.search(t)}
        if "isbn" in kinds or len(kinds) >= 2:
            scored.append((-len(kinds), idx, t))
    blocks = []
    for _, _, t in sorted(scored)[:MAX_COPYRIGHT_BLOCKS]:
        m = _COPYRIGHT_MARK.search(t)
        blocks.append(t if len(t) <= 2 * COPYRIGHT_WINDOW or not m else t[max(0, m.start() - COPYRIGHT_WINDOW): m.end() + COPYRIGHT_WINDOW])
    copyright_text = "\n".join(blocks)

    isbns = find_labelled_isbns(front_text + "\n" + copyright_text)
    for item in find_labelled_isbns(body):
        if item["isbn"] not in {i["isbn"] for i in isbns}:
            item["where"] = "body"
            isbns.append(item)

    disclaimers = find_disclaimers(front_text)
    strong = any(d["strength"] == "strong" for d in disclaimers)
    summary_file = bool(disclaimers) and words < SUMMARY_WORD_CEILING and (strong or words < SUMMARY_WORD_CEILING // 2)

    nonempty = [t for t in titles if t and not re.fullmatch(r"(?i)(cover|unknown|untitled|contents|table of contents)", t)]
    doc_title = ""
    if nonempty:
        top, count = Counter(nonempty).most_common(1)[0]
        if count >= max(2, 0.4 * len(spine)):
            doc_title = top

    chapters = _chapters(reader, opf, manifest)
    publisher_lines = [l.strip()[:120] for l in _PUBLISHER_LINE.findall(copyright_text)][:5]

    return {
        "evidence_version": EVIDENCE_VERSION,
        "status": "ok",
        "reason": "",
        "format": "epub",
        "claims": claims,
        "isbns_in_text": isbns,
        "disclaimers": disclaimers,
        "words": words,
        "chapters": chapters if chapters else len(spine),
        "spine_docs": len(spine),
        "language": claims["language"][:1][0] if claims["language"] else "",
        "english_ratio": english_ratio(body[:200000]),
        "front_norm": norm_text(front_text),
        "copyright_norm": norm_text(copyright_text),
        "doc_title": doc_title,
        "summary_file": summary_file,
        "publisher_lines": publisher_lines,
        "name_hits": name_hits(norm_text(body), probe_names),
        "drm": None,
    }


def _insufficient(fmt, reason):
    return {"evidence_version": EVIDENCE_VERSION, "status": "insufficient", "reason": reason, "format": fmt,
            "claims": {"title": [], "creators": [], "publisher": [], "language": [], "identifiers": [], "isbns": [],
                       "series": None, "series_index": None},
            "isbns_in_text": [], "disclaimers": [], "words": None, "chapters": None, "spine_docs": None,
            "language": "", "english_ratio": None, "front_norm": "", "copyright_norm": "", "doc_title": "",
            "summary_file": False, "publisher_lines": [], "name_hits": {}, "drm": None}


# What other formats could give, and why v1 does not guess:
#  AZW3/MOBI: EXTH 100/503/104 (author/title/ISBN) are claims only; body text needs calibre's
#             ebook-convert (5-30 s per book) - fine for a batch tool, not for ingest. Not done in v1.
#  PDF:       pdftotext of the first pages if the binary exists; scanned PDFs have no text at all.
#  TXT/other: word count only, no title page. None of these are inspected: "insufficient".
FORMAT_NOTES = {
    "azw3": "claims-only via EXTH header; body needs ebook-convert; not inspected in v1",
    "mobi": "claims-only via EXTH header; body needs ebook-convert; not inspected in v1",
    "pdf": "first pages via pdftotext when present; scanned PDFs have no text; not inspected in v1",
}


def extract(path, probe_names=()):
    """probe_names: author names to look for anywhere in the body (see name_hits)."""
    ext = posixpath.splitext(str(path))[1].lower().lstrip(".")
    if ext in ("epub", "kepub"):
        return extract_epub(path, probe_names)
    return _insufficient(ext or "unknown", FORMAT_NOTES.get(ext, "format not supported; only EPUB is read"))
