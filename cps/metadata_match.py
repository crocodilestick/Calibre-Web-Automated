# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Check provider candidates against the book file itself (auto metadata fetch on ingest).

Pure functions, stdlib only, no cps imports. ``book_evidence.extract()`` reads the EPUB once;
``assess_candidate`` / ``rank_candidates`` say whether a provider record is the book that file is.

The rule: the book file is the witness. A candidate is only applied when the title and author
printed in the book back it, and anything the book contradicts (a summary or compilation record,
an author the book never prints, a different volume number) is vetoed whatever its score.

This is the candidate half of a standalone review tool's core, copied function for function so the
two can be diffed; the record-review half is not needed here and is left out.
"""

import re
from difflib import SequenceMatcher

from .book_evidence import find_disclaimers, norm_text, normalize_isbn

CORE_VERSION = 2

# ---------------------------------------------------------------- thresholds (one place)
AUTO_APPLY = 0.80        # minimum confidence for a change to be applied without a person
MARGIN = 0.30            # a replacement title must beat the current record's support by this much
TITLE_SIM_SAME = 0.92    # NextGen #1197's fuzzy bar for "same title"
PRINTED = 0.9            # title/author support at or above this counts as "printed in the book"
WORDS_PER_PAGE_MAX = 1000
WORDS_PER_PAGE_MIN = 40
MIN_WORDS_FOR_RATIO = 20000
MIN_WORDS_TO_JUDGE = 300

W_FRONT_TITLE = 0.40     # title printed in the front matter / copyright page
W_FRONT_AUTHOR = 0.30    # author printed there
W_ISBN = 0.20            # an ISBN printed in the book resolves to a provider record that agrees
W_CLAIMS = 0.10          # embedded OPF / document <title> claims agree (weak: often copied from the DB)

# ---------------------------------------------------------------- vocabulary

JUNK_TITLE = re.compile(
    r"\bsummary\s+of\b|^\s*summary\b|\bunofficial\s+summary\b|\bbook\s+summary\b|\bsummary\s*(?:and|&)\s*analysis\b"
    r"|\bstudy\s+guide\b|\bworkbook\b|\banalysis\s+of\b|\bkey\s+takeaways\b|\bconversation\s+starters\b"
    r"|\btrivia\b|\bquiz\s*book\b|\bcliffs?\s*notes\b|\bspark\s*notes\b|\bbooks\s+by\b|\bcollection\s+set\b"
    r"|\bbox(?:ed)?\s*set\b|\b\d+\s+books?\s+(?:collection|set|bundle)\b|\b\d+\s+books?\s+in\s+1\b"
    r"|\bbeginner'?s\s+guide\s+to\b|\bguide\s+to\s+(?:the\s+)?(?:novel|book)\b"
    r"|\b(?:two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(?:more\s+)?(?:[\w']+\s+){0,3}(?:novellas|novels|stories|books)\b"
    r"|\bfree\s+preview\b|\bsampler\b|\bfirst\s+\d+\s+chapters\b",
    re.I,
)
# Not a different book, but a different *product* or a provider's marketing text glued onto the title.
JUNK_TITLE_TAIL = re.compile(
    r"\blow\s+price\s+cd\b|\baudio\s*cd\b|\bmp3\s*cd\b|\baudiobook\b|\bunabridged\b|\babridged\b"
    r"|\bthe\s+latest\s+thrilling\b|\bbestselling\s+series\b|\bsunday\s+times\s+bestsell|\bnew\s+york\s+times\s+bestsell"
    r"|\ban?\s+(?:electrifying|gripping|thrilling|stunning)\s+\w+",
    re.I,
)
JUNK_NAMES = (
    "readtrepreneur", "powerful insights", "irb media", "books llc", "instaread", "quick savant", "brief books",
    "companionreads", "abookaday", "flash reads", "success notes", "supersummary", "bookrags", "worth books",
    "bright summaries",
)
_JUNK_NAME_RE = re.compile("|".join(re.escape(n).replace(r"\ ", r"\s*") for n in JUNK_NAMES), re.I)

COLLECTION_WORDS = frozenset({"omnibus", "boxed", "boxset", "bundle", "megapack", "anthology", "compendium",
                              "trilogy", "duology", "volumes", "vols"})
_BUNDLE_RANGE = re.compile(
    r"\bbooks?\s*\d{1,3}\s*(?:-|–|to|thru|through)\s*\d{1,3}\b|\(#?\d{1,3}\s*[-–]\s*\d{1,3}\)"
    r"|\ball\s+\d+\s+books\b|\b\d+\s+books\b", re.I)
_FORMAT_JUNK = re.compile(
    r"\(\s*(?:pdfdrive(?:\.com)?|z-?lib(?:\.org)?|txt|epub|mobi|pdf|n|retail|ebook)\s*\)|\[\s*(?:ebook|epub|retail)\s*\]"
    r"|\.(?:epub|mobi|azw3|pdf|txt)$|\bpdfdrive\.com\b",
    re.I,
)
_DEGREE = re.compile(r"^(?:ph\.?\s*d\.?|m\.?\s*d\.?|jr\.?|sr\.?|dr\.?|esq\.?|ii|iii|iv|mba|msc|bsc|rn|lcsw)$", re.I)
_FILENAME_STYLE = re.compile(r"^(?P<a>[^-]{3,60}?)\s+-\s+(?P<s>[^-]+?)\s+(?P<n>\d+[a-z]?(?:\.\d+)?)\s+-\s+(?P<t>.+)$")
_SERIES_DASH = re.compile(r"^(?P<s>[^-:]+?)\s+(?P<n>\d+[a-z]?(?:\.\d+)?)\s+-\s+(?P<t>.+)$")
_DEGREE_TAIL = re.compile(r"(?:\s+(?:ph\.?\s*d\.?|m\.?\s*d\.?|jr\.?|sr\.?|esq\.?|mba|lcsw))+\s*$", re.I)
_USERNAME = re.compile(r"^[A-Za-z]+[0-9]{2,}$|^[A-Za-z0-9_.]+@")
_SERIES_PREFIX = re.compile(r"^(?P<series>.+?)\s+(?P<index>\d+[a-z]?(?:\.\d+)?)\s*:\s+(?P<rest>.+)$")
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+")
_TRAILING_ARTICLE = re.compile(r",\s*(?:the|a|an)\s*$", re.I)   # "Appetite for Wonder, An"


# ---------------------------------------------------------------- titles

def split_series_prefix(title):
    """'Alex Cross 07: Cat & Mouse' -> ('Alex Cross', '07', 'Cat & Mouse'). The prefix is the operator's convention."""
    m = _SERIES_PREFIX.match(title or "")
    if m:
        return m.group("series"), m.group("index"), m.group("rest")
    return None, None, title or ""


def clean_claim_title(title):
    """Remove download-site and format junk from an embedded title, filename or folder name."""
    t = _FORMAT_JUNK.sub(" ", title or "")
    t = re.sub(r"\s*\(\d+\)\s*$", "", t)                      # calibre folder suffix "(196)"
    t = re.sub(r"(\w)_ ", r"\1: ", t)                        # calibre folders turn ':' into '_'
    t = re.sub(r"\s+", " ", t).strip(" -_.")
    # filename style 'Author - Series 02 - Title' / 'Series 6 - Title' -> 'Series 02: Title'
    m = _FILENAME_STYLE.match(t) or _SERIES_DASH.match(t)
    if m:
        t = "%s %s: %s" % (m.group("s"), m.group("n"), m.group("t"))
    return t


def main_title(title):
    """Title without series prefix, bracketed asides and subtitle."""
    _, _, rest = split_series_prefix(clean_claim_title(title))
    rest = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", rest)
    rest = re.split(r"\s*:\s+|\s+[-–—]\s+|\s*/\s*", rest)[0]
    rest = _TRAILING_ARTICLE.sub("", rest)
    return re.sub(r"\s+", " ", rest).strip()


def title_key(title):
    return _LEADING_ARTICLE.sub("", norm_text(main_title(title)))


def full_key(title):
    _, _, rest = split_series_prefix(clean_claim_title(title))
    return _LEADING_ARTICLE.sub("", norm_text(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", rest)))


def title_similarity(a, b):
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    fa, fb = full_key(a), full_key(b)
    if (len(ka.split()) >= 2 and _phrase_in(ka, " " + fb + " ")) or (len(kb.split()) >= 2 and _phrase_in(kb, " " + fa + " ")):
        return 0.95      # 'The Horse and His Boy' inside 'The Chronicles of Narnia - The Horse and His Boy'
    sa, sb = set(ka.split()), set(kb.split())
    jac = len(sa & sb) / len(sa | sb)
    return round(max(jac, SequenceMatcher(None, ka, kb).ratio()), 3)


def digits(title):
    _, _, rest = split_series_prefix(title or "")
    rest = re.sub(r"\b\d+(?:st|nd|rd|th)\s+anniversary\b|\b(?:19|20)\d\d\b", " ", rest, flags=re.I)
    return set(re.findall(r"\d+", rest))


# ---------------------------------------------------------------- people

def clean_author(name):
    """Calibre stores ',' inside an author name as '|'. Drop '(ill. X)' asides and degrees for matching."""
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", (name or "").replace("|", ","))
    parts = [p.strip() for p in s.split(",") if p.strip()]
    keep = [p for p in parts if not _DEGREE.match(p)]
    out = re.sub(r"\s+", " ", " ".join(keep)).strip()
    return _DEGREE_TAIL.sub("", out).strip()


def split_merged(name):
    """'George R. R. Martin,George R R Martin' (two names in one entry) -> both names. A 'Last, First' stays one."""
    parts = [p.strip() for p in re.split(r"[|,]", re.sub(r"\([^)]*\)", " ", name or "")) if p.strip()]
    parts = [p for p in parts if not _DEGREE.match(p)]
    if len(parts) >= 2 and all(len(p.split()) >= 2 for p in parts):
        return parts
    return [name]


def _ntoks(name):
    return norm_text(clean_author(name)).split()


def same_person(a, b):
    """Order-independent and initial-tolerant: 'Child Lee' = 'Lee Child', 'J. Patterson' = 'James Patterson'.

    Surnames must match: 'Lee Tobin McClain' is not 'Lee Child' although both are 'Lee'.
    """
    ta, tb = _ntoks(a), _ntoks(b)
    if not ta or not tb:
        return False
    if set(ta) == set(tb):
        return True
    if len(ta) == 1 or len(tb) == 1:
        one, other = (ta, tb) if len(ta) == 1 else (tb, ta)
        return len(one[0]) >= 3 and one[0] in other
    if ta[-1] != tb[-1]:
        return False
    return ta[0][0] == tb[0][0]


def authors_agree(a_list, b_list):
    return any(same_person(x, y) for a in a_list or [] for x in split_merged(a) for b in b_list or [] for y in split_merged(b))


# ---------------------------------------------------------------- evidence lookups

def _phrase_in(phrase, hay):
    return bool(phrase) and (" " + phrase + " ") in hay


def _hay(evidence):
    return " " + (evidence.get("front_norm") or "") + " " + (evidence.get("copyright_norm") or "") + " "


def title_support(title, evidence):
    """1.0 title printed as a phrase; 0.9 printed with drop-cap spacing ('a g ame of t hrones');
    0.6 every word present but not together; else 0."""
    hay = _hay(evidence)
    key = title_key(title)
    if not key:
        return 0.0
    if _phrase_in(key, hay):
        return 1.0
    if "*" in (title or ""):
        # 'F*ck' in the record, 'Fuck' in the book. A starred letter or three, inside one word.
        starred = title_key((title or "").replace("*", "qxzq"))
        pattern = re.escape(" " + starred + " ").replace("qxzq", "[a-z]{0,3}")
        if "[a-z]" in pattern and re.search(pattern, hay):
            return 1.0
    squashed = key.replace(" ", "")
    if len(squashed) >= 8 and re.search(r"[a-z]{3}", squashed) and squashed in hay.replace(" ", ""):
        return 0.9
    words = set(key.split())
    return 0.6 if len(words) >= 2 and words <= set(hay.split()) else 0.0


def name_support(name, evidence):
    """1.0 full name printed (either order); 0.7 surname printed; else 0."""
    hay = _hay(evidence)
    toks = _ntoks(name)
    if len(toks) < 2:
        return 0.0          # a single word ('Andrew', 'Jack') is printed everywhere; it proves nothing
    if (_phrase_in(" ".join(toks), hay) or _phrase_in(" ".join(toks[1:] + toks[:1]), hay)
            or _phrase_in(" ".join(toks[-1:] + toks[:-1]), hay)):
        return 1.0
    if len(toks) >= 2 and "".join(toks) in hay.replace(" ", "") and len("".join(toks)) >= 8:
        return 1.0
    sn = toks[-1]
    return 0.7 if len(sn) >= 3 and _phrase_in(sn, hay) else 0.0


def author_support(authors, evidence):
    """Best support of any listed author (an illustrator listed first must not hide the printed author)."""
    return max([name_support(p, evidence) for a in authors or [] for p in split_merged(a)] or [0.0])


def claim_junk(evidence):
    """Junk markers on the file's own embedded claims (the 5 counter-examples)."""
    c = evidence.get("claims") or {}
    titles = c.get("title") or []
    creators = [x["name"] for x in c.get("creators") or []]
    out = {"title": [], "creators": []}
    for t in titles:
        if normalize_isbn(re.sub(r"\(.*?\)", "", t)) or re.search(r"\b\d{9}[\dXx]\b|\b97[89]\d{10}\b", t):
            out["title"].append("title is or contains an ISBN")
        if _FORMAT_JUNK.search(t):
            out["title"].append("format/download-site marker in title")
        if any(norm_text(t) == norm_text(cr) for cr in creators):
            out["title"].append("title equals the creator")
    if any(_FORMAT_JUNK.search(cr) for cr in creators) and titles:
        out["title"].append("creator carries a format marker, so the title claim is unreliable too (swapped fields?)")
    for cr in creators:
        if not re.search(r"[A-Za-z]", cr):
            out["creators"].append("creator has no letters: %r" % cr)
        elif _USERNAME.search(cr.strip()):
            out["creators"].append("creator looks like a username: %r" % cr)
        elif _FORMAT_JUNK.search(cr):
            out["creators"].append("format marker in creator: %r" % cr)
        elif norm_text(cr) in ("unknown", "anonymous", "admin", "user"):
            out["creators"].append("placeholder creator %r" % cr)
        elif any(norm_text(cr) in (norm_text(clean_claim_title(t)), norm_text(main_title(t))) for t in titles):
            out["creators"].append("creator equals the title: %r" % cr)
        elif len(norm_text(cr).split()) == 1 and any(norm_text(cr) in norm_text(t).split() for t in titles):
            out["creators"].append("creator is a single word of the title: %r" % cr)
    return out


def claim_titles(evidence):
    """Non-junk title claims from the file: OPF dc:title and the dominant document <title>."""
    c = evidence.get("claims") or {}
    out = []
    if not claim_junk(evidence)["title"]:
        out += [("opf", clean_claim_title(t)) for t in (c.get("title") or [])[:1]]
    if evidence.get("doc_title"):
        out.append(("doc-title", clean_claim_title(evidence["doc_title"])))
    return [(s, t) for s, t in out if t]


def claim_creators(evidence):
    c = evidence.get("claims") or {}
    if claim_junk(evidence)["creators"]:
        return []
    return [p for x in c.get("creators") or [] for p in split_merged(x["name"])]


# ---------------------------------------------------------------- junk checks on records and candidates

def junk_title_reasons(title, book_titles=()):
    """Reasons a title is not the book itself. A marker the book's own title carries is not junk."""
    own = " ".join(book_titles)
    reasons = []
    for rx, label in ((JUNK_TITLE, "summary/guide/compilation pattern"), (JUNK_TITLE_TAIL, "marketing or audio-product text")):
        m = rx.search(title or "")
        if m and not re.search(re.escape(m.group(0)), own, re.I):
            reasons.append("%s: %r" % (label, m.group(0)))
    coll = (set(norm_text(title).split()) & COLLECTION_WORDS) - set(norm_text(own).split())
    if coll:
        reasons.append("collection word(s) %s" % sorted(coll))
    for m in _BUNDLE_RANGE.finditer(title or ""):
        if not re.search(re.escape(m.group(0)), own, re.I):
            reasons.append("bundle marker %r" % m.group(0))
            break
    return reasons


def junk_name_reasons(names):
    return ["known summary/compilation publisher or author %r" % n for n in names or [] if n and _JUNK_NAME_RE.search(n)]


# ---------------------------------------------------------------- ingest-style candidate assessment

def assess_candidate(evidence, cand, book_titles=None):
    """Score one provider candidate against the book. Vetoes block applying it whatever the score."""
    book_titles = book_titles if book_titles is not None else [t for _, t in claim_titles(evidence)]
    vetoes = []
    vetoes += junk_title_reasons(" ".join(filter(None, [cand.get("title"), cand.get("subtitle")])), book_titles)
    vetoes += junk_name_reasons((cand.get("authors") or []) + (cand.get("publishers") or []))
    a_sup = author_support(cand.get("authors"), evidence)
    if cand.get("authors") and a_sup == 0.0 and not authors_agree(cand["authors"], claim_creators(evidence)):
        vetoes.append("author not printed in the book and not the file's creator")
    t_sup = title_support(cand.get("title"), evidence)
    if t_sup == 0.0 and not any(title_similarity(cand.get("title"), t) >= TITLE_SIM_SAME for t in book_titles):
        vetoes.append("title not printed in the book and not the file's title")
    cd = digits(cand.get("title"))
    for t in book_titles:
        if cd and digits(t) and cd != digits(t):
            vetoes.append("numbers differ: %s vs %s" % (sorted(cd), sorted(digits(t))))
            break
    words, pages = evidence.get("words") or 0, cand.get("pages")
    if pages and words:
        ratio = words / pages
        if ratio > WORDS_PER_PAGE_MAX:
            vetoes.append("file has %d words for a %d-page candidate (summary or abridged record?)" % (words, pages))
        elif ratio < WORDS_PER_PAGE_MIN and words > MIN_WORDS_FOR_RATIO:
            vetoes.append("candidate has %d pages for a %d-word file (omnibus?)" % (pages, words))
    if evidence.get("summary_file"):
        vetoes.append("the file itself looks like a summary (front-matter disclaimer, %s words)" % words)
    printed = {i["isbn"] for i in evidence.get("isbns_in_text") or []}
    isbn_hit = bool(printed & set(cand.get("isbns") or []))
    score = W_FRONT_TITLE * min(t_sup, 1.0) + W_FRONT_AUTHOR * a_sup + W_ISBN * isbn_hit
    if book_titles:
        score += W_CLAIMS * (sum(1 for t in book_titles if title_similarity(cand.get("title"), t) >= TITLE_SIM_SAME) / len(book_titles))
    return round(score, 3), vetoes, ["title printed=%s author printed=%s isbn-in-book=%s" % (t_sup, a_sup, isbn_hit)]


def rank_candidates(evidence, candidates):
    """Best surviving candidate and its margin over the next *different work*. Nothing survives -> (None, 0, ranked)."""
    ranked = []
    for c in candidates:
        s, v, r = assess_candidate(evidence, c)
        ranked.append({"candidate": c, "score": s, "vetoes": v, "reasons": r})
    ranked.sort(key=lambda x: -x["score"])
    alive = [x for x in ranked if not x["vetoes"]]
    if not alive:
        return None, 0.0, ranked
    best = alive[0]
    others = [x for x in alive[1:] if title_key(x["candidate"]["title"]) != title_key(best["candidate"]["title"])
              or not authors_agree(x["candidate"].get("authors"), best["candidate"].get("authors"))]
    margin = best["score"] - (others[0]["score"] if others else 0.0)
    return best, round(margin, 3), ranked
