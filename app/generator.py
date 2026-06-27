"""Content generation with web search for real, factual content."""
import re
from .config import settings

SYSTEM_PROMPT = (
    "You are an expert SEO content writer and researcher. Use web search to ground "
    "the article in real, current, verifiable facts. The piece MUST include concrete "
    "specifics: real figures, dates, named organisations, laws or regulations where "
    "relevant, and real examples. Cite sources inline as markdown links to the actual "
    "pages you used. Never invent statistics or sources. If a fact cannot be verified, "
    "omit it rather than guess.\n\n"
    "Return your answer in EXACTLY this format, with these labels on their own lines. "
    "Do not add anything before TITLE or after the draft. Do not use code fences.\n\n"
    "TITLE: <SEO title, 60 chars or fewer, contains the keyword>\n"
    "META: <meta description, 120-160 chars, contains the keyword>\n"
    "SLUG: <lowercase-hyphenated-url-slug>\n"
    "BRIEF: <2-3 sentences on what the piece covers and who it is for>\n"
    "DRAFT:\n"
    "<the full article in markdown: one H1, several H2 sections, keyword in the title, "
    "first paragraph and at least one heading, real cited facts with markdown links, "
    "600+ words. Write in the requested tone.>"
)


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s-]", "", (text or "").lower())
    return re.sub(r"[\s-]+", "-", text).strip("-")[:60]


def _parse(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:markdown|json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    parts = re.split(r"(?im)^\s*DRAFT:\s*$", text, maxsplit=1)
    head = parts[0]
    draft = parts[1].strip() if len(parts) > 1 else ""
    if not draft:
        m = re.search(r"(?is)DRAFT:\s*(.+)$", text)
        draft = m.group(1).strip() if m else text
    out = {}
    for key, label in [("title", "TITLE"), ("meta_description", "META"),
                       ("slug", "SLUG"), ("brief", "BRIEF")]:
        mm = re.search(rf"(?im)^\s*{label}:\s*(.+?)\s*$", head)
        if mm:
            out[key] = mm.group(1).strip()
    out["draft"] = draft
    return out


def _demo_piece(keyword: str, content_type: str, tone: str) -> dict:
    kw = keyword.strip(); kw_title = kw.title()
    return {
        "title": f"{kw_title}: A Practical Guide"[:60],
        "meta_description": (f"A practical, no-nonsense guide to {kw}. Learn what "
                             f"matters, what to avoid, and how to get results.")[:158],
        "slug": _slugify(f"{kw}-guide"),
        "brief": (f"A {tone} {content_type} introducing {kw}. (Demo content — add your "
                  f"Anthropic API key in .env to generate real, researched drafts.)"),
        "draft": (f"# {kw_title}: A Practical Guide\n\nIf you are exploring {kw}, you "
                  f"are in the right place. Read more on the [official docs](https://example.com).\n\n"
                  f"## Why {kw_title} matters\n\nGetting {kw} right saves effort.\n\n"
                  f"## Getting started\n\nPick one step and act on it today.\n\n"
                  f"*This is demo output. Set ANTHROPIC_API_KEY in your .env file.*"),
        "demo": True,
    }


def _call(client, model, user, use_search):
    kwargs = dict(model=model, max_tokens=4000, system=SYSTEM_PROMPT,
                  messages=[{"role": "user", "content": user}])
    if use_search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search",
                            "max_uses": 4}]
    resp = client.messages.create(**kwargs)
    return "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", "") == "text")


def generate(keyword: str, content_type: str = "blog", tone: str = "professional") -> dict:
    if not settings.anthropic_api_key:
        return _demo_piece(keyword, content_type, tone)
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    user = f"Target keyword: {keyword}\nContent type: {content_type}\nTone: {tone}"
    last_err = None
    for use_search in (True, False):
        try:
            text = _call(client, settings.anthropic_model, user, use_search)
            data = _parse(text)
            if not data.get("draft") or len(data["draft"]) < 80:
                raise ValueError("empty or too-short draft")
            data.setdefault("slug", _slugify(data.get("title", keyword)))
            data.setdefault("title", keyword.title())
            data.setdefault("meta_description", "")
            data.setdefault("brief", "")
            data["demo"] = False
            return data
        except Exception as e:
            last_err = e
            continue
    fallback = _demo_piece(keyword, content_type, tone)
    fallback["error"] = f"Generation failed ({last_err}); showing demo content."
    return fallback
