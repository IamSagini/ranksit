"""Rule-based SEO scorer (deep audit)."""
import re
from dataclasses import dataclass, asdict


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    fix: str
    weight: int
    category: str


_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_VOWEL_GROUPS = re.compile(r"[aeiouy]+", re.IGNORECASE)


def _words(text):
    return _WORD_RE.findall(text or "")


def _sentences(text):
    return [p for p in re.split(r"[.!?]+", text or "") if p.strip()]


def _paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _strip_markdown(text):
    text = re.sub(r"`{1,3}[^`]*`{1,3}", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_>#-]", " ", text)
    return text


def _syllables(word):
    word = word.lower()
    count = len(_VOWEL_GROUPS.findall(word))
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def _flesch(text):
    words = _words(text); sents = _sentences(text)
    if not words or not sents:
        return 0.0
    syl = sum(_syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words)/len(sents)) - 84.6 * (syl/len(words)), 1)


def _headings(text):
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


def score_content(*, keyword, title, meta_description, slug, draft, target_words=300):
    kw = (keyword or "").strip().lower()
    prose = _strip_markdown(draft)
    body_words = _words(prose)
    wc = len(body_words)
    body_lower = prose.lower()
    headings = _headings(draft)
    sents = _sentences(prose)
    avg_sent = round(len(body_words) / len(sents), 1) if sents else 0
    paras = _paragraphs(_strip_markdown(re.sub(r"^#{1,6}.*$", "", draft, flags=re.MULTILINE)))
    longest_para = max((len(_words(p)) for p in paras), default=0)
    all_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", draft or "")
    ext_links = [u for u in all_links if u.startswith("http")]
    has_list = bool(re.search(r"^\s*([-*]|\d+\.)\s+", draft or "", re.MULTILINE))
    has_numbers = bool(re.search(r"\d", prose))
    flesch = _flesch(prose)
    C = []

    in_title = bool(kw) and kw in (title or "").lower()
    C.append(Check("Keyword in title", in_title, "Found in title" if in_title else "Missing from title",
                   "Work the target keyword into the title, ideally near the front.", 12, "Keyword"))
    in_intro = bool(kw) and kw in " ".join(body_words[:60]).lower()
    C.append(Check("Keyword in intro", in_intro, "Found in opening" if in_intro else "Not in first 60 words",
                   "Mention the keyword within the first paragraph.", 10, "Keyword"))
    in_heading = bool(kw) and any(kw in h.lower() for _, h in headings)
    C.append(Check("Keyword in a heading", in_heading, "Present in a subheading" if in_heading else "No heading uses it",
                   "Add the keyword or a close variant to at least one H2.", 8, "Keyword"))
    density = (body_lower.count(kw) / wc * 100) if (kw and wc) else 0
    C.append(Check("Keyword density", 0.5 <= density <= 2.5, f"{density:.1f}% of body",
                   "Aim for 0.5-2.5%. Below reads thin; above reads stuffed.", 8, "Keyword"))
    in_meta = bool(kw) and kw in (meta_description or "").lower()
    C.append(Check("Keyword in meta description", in_meta, "Present" if in_meta else "Missing from meta",
                   "Include the keyword in the meta description.", 6, "Keyword"))
    in_slug = bool(kw) and kw.replace(" ", "-") in (slug or "").lower()
    C.append(Check("Keyword in URL slug", in_slug, "Present in slug" if in_slug else "Missing from slug",
                   "Put the keyword in the slug, hyphen-separated.", 6, "Keyword"))

    tlen = len(title or "")
    C.append(Check("Title length", 0 < tlen <= 60, f"{tlen} characters",
                   "Keep the title at 60 characters or fewer.", 8, "Metadata"))
    C.append(Check("Title not too short", tlen >= 30, f"{tlen} characters",
                   "Use at least 30 characters so the title is descriptive.", 4, "Metadata"))
    mlen = len(meta_description or "")
    C.append(Check("Meta description length", 120 <= mlen <= 160, f"{mlen} characters",
                   "Write a meta description between 120 and 160 characters.", 10, "Metadata"))
    clean_slug = bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug or ""))
    C.append(Check("Clean URL slug", clean_slug, slug or "(empty)",
                   "Use a lowercase, hyphen-separated slug.", 6, "Metadata"))

    h1 = sum(1 for lvl, _ in headings if lvl == 1)
    C.append(Check("Single H1", h1 == 1, f"{h1} H1 heading(s)",
                   "Use exactly one H1, everything else H2 or lower.", 8, "Structure"))
    h2 = sum(1 for lvl, _ in headings if lvl == 2)
    C.append(Check("Heading structure", h2 >= 2, f"{h2} H2 subheading(s)",
                   "Break the article into at least two H2 sections.", 8, "Structure"))
    C.append(Check("Short paragraphs", longest_para <= 150, f"longest {longest_para} words",
                   "Keep paragraphs under ~150 words for skimmability.", 5, "Structure"))
    C.append(Check("Uses a list", has_list, "List present" if has_list else "No lists",
                   "Add a bulleted or numbered list to break up the text.", 4, "Structure"))

    C.append(Check("Readability", flesch >= 50, f"Flesch {flesch}",
                   "Shorten sentences and simplify wording to lift above 50.", 8, "Readability"))
    C.append(Check("Sentence length", 0 < avg_sent <= 25, f"avg {avg_sent} words",
                   "Keep average sentence length at 25 words or fewer.", 6, "Readability"))
    C.append(Check("Word count", wc >= target_words, f"{wc} words",
                   f"Aim for at least {target_words} words.", 6, "Readability"))

    C.append(Check("Cites sources", len(ext_links) >= 1, f"{len(ext_links)} external link(s)",
                   "Cite at least one external source as a link.", 6, "Evidence"))
    C.append(Check("Multiple sources", len(ext_links) >= 2, f"{len(ext_links)} external link(s)",
                   "Cite two or more sources for credibility.", 4, "Evidence"))
    C.append(Check("Includes data", has_numbers, "Figures present" if has_numbers else "No figures",
                   "Add concrete figures or statistics to back claims.", 4, "Evidence"))

    total_w = sum(c.weight for c in C)
    earned = sum(c.weight for c in C if c.passed)
    score = round(earned / total_w * 100) if total_w else 0

    cats = {}
    for c in C:
        d = cats.setdefault(c.category, {"name": c.category, "passed": 0, "total": 0, "w": 0, "ew": 0})
        d["total"] += 1; d["w"] += c.weight
        if c.passed:
            d["passed"] += 1; d["ew"] += c.weight
    categories = []
    for name in ["Keyword", "Metadata", "Structure", "Readability", "Evidence"]:
        if name in cats:
            d = cats[name]
            d["subscore"] = round(d["ew"] / d["w"] * 100) if d["w"] else 0
            categories.append(d)

    metrics = {"words": wc, "reading_time": max(1, round(wc / 200)), "avg_sentence": avg_sent,
               "links": len(all_links), "headings": len(headings), "flesch": flesch}

    return {"score": score, "checks": [asdict(c) for c in C], "passed": sum(1 for c in C if c.passed),
            "total": len(C), "categories": categories, "metrics": metrics}
