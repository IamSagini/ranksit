# Rankcraft

An AI content and SEO platform. Generate publish-ready content from a target
keyword, then score it against twelve rule-based SEO checks with concrete fixes.
Built with FastAPI, HTMX and Jinja2. No build step, no frontend toolchain.

## What it does

- Enter a keyword, content type and tone, and generate a title, meta
  description, slug and full markdown draft (Anthropic API).
- Live SEO score (0-100) that updates as you edit, with a pass/fail breakdown
  and a specific fix for every failing check.
- Save pieces to a library, mark them published, export to markdown.

The SEO scorer is pure Python and needs no API key, so the whole app runs and
scores content out of the box. Add an Anthropic key for real generation.

## Run it

The quick way:

```bash
./run.sh
```

Or manually:

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000

## Real content generation

By default the app runs in demo mode and returns placeholder drafts. To
generate real content, copy `.env.example` to `.env` and add your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Restart the server. Scoring works identically in both modes.

## Project layout

```
app/
  main.py        FastAPI app and routes
  scorer.py      rule-based SEO scoring (no API)
  generator.py   Anthropic generation with demo fallback
  models.py      SQLModel content table
  config.py      settings
  templates/     Jinja2 + HTMX pages
  static/        stylesheet
```

## Deploy notes

SQLite is used for local development. For deployment, set `DATABASE_URL` in
`.env` to a MySQL or Postgres connection string. The next planned addition is
live keyword volume and rank tracking via a SERP API (stubbed for now).
