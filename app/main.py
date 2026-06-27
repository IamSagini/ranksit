from datetime import datetime
from io import BytesIO
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from .config import settings
import markdown as md
from .models import ContentPiece, User, PieceLike, GenerationLog, init_db, engine
from .scorer import score_content
from .generator import generate
from . import auth

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
init_db()


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(request, "page_about.html", _ctx(request))


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse(request, "page_privacy.html", _ctx(request))


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return templates.TemplateResponse(request, "page_terms.html", _ctx(request))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("app/static/favicon.svg", media_type="image/svg+xml")


def get_session():
    with Session(engine) as session:
        yield session


def _ctx(request: Request, **extra):
    base = {"app_name": settings.app_name, "demo_mode": not settings.anthropic_api_key,
            "user": auth.current_user(request),
            "year": __import__("datetime").datetime.utcnow().year}
    base.update(extra)
    return base


DAILY_LIMIT = 10


def _used_today(session, user_id):
    from datetime import datetime as _dt
    day = _dt.utcnow().strftime("%Y-%m-%d")
    return len(session.exec(select(GenerationLog).where(GenerationLog.user_id == user_id, GenerationLog.day == day)).all())


def _log_generation(session, user_id):
    from datetime import datetime as _dt
    day = _dt.utcnow().strftime("%Y-%m-%d")
    session.add(GenerationLog(user_id=user_id, day=day)); session.commit()


def _score(p: dict) -> dict:
    return score_content(keyword=p.get("keyword",""), title=p.get("title",""),
                         meta_description=p.get("meta_description",""),
                         slug=p.get("slug",""), draft=p.get("draft",""))


def _like_count(session, piece_id):
    return len(session.exec(select(PieceLike).where(PieceLike.piece_id == piece_id)).all())


def _user_liked(session, piece_id, user_id):
    return session.exec(select(PieceLike).where(PieceLike.piece_id == piece_id, PieceLike.user_id == user_id)).first() is not None


def _render_markdown(text):
    import re
    html = md.markdown(text or "", extensions=["extra", "sane_lists"])
    html = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener noreferrer"', html)
    return html


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, keyword: str = ""):
    if auth.current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "signup.html", _ctx(request, try_keyword=keyword))


@app.post("/signup")
def signup(request: Request, name: str = Form(...), email: str = Form(...),
           password: str = Form(...), session: Session = Depends(get_session)):
    email = email.strip().lower()
    if len(password) < 8:
        return templates.TemplateResponse(request, "signup.html", _ctx(request, error="Password must be at least 8 characters."))
    if session.exec(select(User).where(User.email == email)).first():
        return templates.TemplateResponse(request, "signup.html", _ctx(request, error="An account with that email already exists."))
    user = User(email=email, name=name.strip(), password_hash=auth.hash_password(password))
    session.add(user); session.commit(); session.refresh(user)
    resp = RedirectResponse("/", status_code=303); auth.login_user(resp, user); return resp


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if auth.current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", _ctx(request))


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          session: Session = Depends(get_session)):
    email = email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not auth.verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", _ctx(request, error="Wrong email or password."))
    resp = RedirectResponse("/", status_code=303); auth.login_user(resp, user); return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303); auth.logout_user(resp); return resp


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user:
        return templates.TemplateResponse(request, "landing.html", _ctx(request))
    pieces = session.exec(select(ContentPiece).where(ContentPiece.user_id == user.id).order_by(ContentPiece.updated_at.desc())).all()
    avg = round(sum(p.score for p in pieces) / len(pieces)) if pieces else 0
    return templates.TemplateResponse(request, "index.html", _ctx(request, pieces=pieces, avg=avg))


@app.get("/new", response_class=HTMLResponse)
def new_form(request: Request):
    if not auth.current_user(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "editor.html", _ctx(request, piece=None, result=None))


@app.post("/generate", response_class=HTMLResponse)
def do_generate(request: Request, keyword: str = Form(...), content_type: str = Form("blog"), tone: str = Form("professional"), session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    used = _used_today(session, user.id)
    if used >= DAILY_LIMIT:
        return templates.TemplateResponse(request, "partials/limit_reached.html", {"limit": DAILY_LIMIT})
    data = generate(keyword, content_type, tone)
    _log_generation(session, user.id)
    piece = {"id": None, "keyword": keyword, "content_type": content_type, "title": data.get("title",""),
             "meta_description": data.get("meta_description",""), "slug": data.get("slug",""),
             "draft": data.get("draft",""), "brief": data.get("brief","")}
    result = _score(piece)
    notice = data.get("error") or ("Demo content — add your API key for real drafts." if data.get("demo") else None)
    remaining = DAILY_LIMIT - (used + 1)
    if not notice and remaining <= 3:
        notice = f"{remaining} generation{'s' if remaining != 1 else ''} left today."
    return templates.TemplateResponse(request, "partials/workspace.html", {"piece": piece, "result": result, "notice": notice})


@app.post("/score", response_class=HTMLResponse)
def do_score(request: Request, keyword: str = Form(""), title: str = Form(""), meta_description: str = Form(""), slug: str = Form(""), draft: str = Form("")):
    result = score_content(keyword=keyword, title=title, meta_description=meta_description, slug=slug, draft=draft)
    return templates.TemplateResponse(request, "partials/score_panel.html", {"result": result})


@app.post("/save")
def save(request: Request, keyword: str = Form(...), content_type: str = Form("blog"), title: str = Form(""),
         meta_description: str = Form(""), slug: str = Form(""), draft: str = Form(""), piece_id: str = Form(""),
         session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    result = score_content(keyword=keyword, title=title, meta_description=meta_description, slug=slug, draft=draft)
    piece = session.get(ContentPiece, int(piece_id)) if piece_id else None
    if piece and piece.user_id != user.id:
        return RedirectResponse("/", status_code=303)
    if piece is None:
        piece = ContentPiece(keyword=keyword, user_id=user.id); session.add(piece)
    piece.keyword=keyword; piece.content_type=content_type; piece.title=title
    piece.meta_description=meta_description; piece.slug=slug; piece.draft=draft
    piece.score=result["score"]; piece.updated_at=datetime.utcnow()
    session.commit(); session.refresh(piece)
    return RedirectResponse(f"/piece/{piece.id}", status_code=303)


@app.get("/piece/{piece_id}", response_class=HTMLResponse)
def view_piece(piece_id: int, request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    piece = session.get(ContentPiece, piece_id)
    if piece is None or piece.user_id != user.id:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "editor.html", _ctx(request, piece=piece.model_dump(), result=_score(piece.model_dump())))


@app.post("/piece/{piece_id}/status")
def toggle_status(piece_id: int, request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request); piece = session.get(ContentPiece, piece_id)
    if user and piece and piece.user_id == user.id:
        piece.is_public = not piece.is_public
        piece.status = "published" if piece.is_public else "draft"
        piece.updated_at = datetime.utcnow(); session.commit()
    return RedirectResponse(f"/piece/{piece_id}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user or not getattr(user, "is_admin", False):
        return RedirectResponse("/", status_code=303)
    import json
    from datetime import timedelta
    users = session.exec(select(User)).all()
    pieces = session.exec(select(ContentPiece)).all()
    likes = session.exec(select(PieceLike)).all()
    published_pieces = [p for p in pieces if p.is_public]
    stats = {"users": len(users), "pieces": len(pieces),
             "published": len(published_pieces), "likes": len(likes)}
    def day(dt):
        return dt.date()
    all_dates = [day(u.created_at) for u in users] + [day(p.created_at) for p in pieces] \
        + [day(p.updated_at) for p in published_pieces] + [day(l.created_at) for l in likes]
    if all_dates:
        start, end = min(all_dates), max(all_dates)
    else:
        start = end = datetime.utcnow().date()
    labels, du, dp, dpub, dl = [], [], [], [], []
    cur = start
    while cur <= end:
        labels.append(cur.strftime("%d %b"))
        du.append(sum(1 for u in users if day(u.created_at) <= cur))
        dp.append(sum(1 for p in pieces if day(p.created_at) <= cur))
        dpub.append(sum(1 for p in published_pieces if day(p.updated_at) <= cur))
        dl.append(sum(1 for l in likes if day(l.created_at) <= cur))
        cur += timedelta(days=1)
    chart = json.dumps({"labels": labels, "users": du, "pieces": dp, "published": dpub, "likes": dl})
    return templates.TemplateResponse(request, "admin.html", _ctx(request, stats=stats, chart=chart))


@app.get("/explore", response_class=HTMLResponse)
def explore(request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    pieces = session.exec(select(ContentPiece).where(ContentPiece.is_public == True).order_by(ContentPiece.updated_at.desc())).all()
    cards = []
    for p in pieces:
        author = session.get(User, p.user_id) if p.user_id else None
        cards.append({"p": p, "author": (author.name or author.email) if author else "Unknown", "count": _like_count(session, p.id), "liked": _user_liked(session, p.id, user.id)})
    return templates.TemplateResponse(request, "explore.html", _ctx(request, cards=cards))


@app.get("/explore/{piece_id}", response_class=HTMLResponse)
def public_piece(piece_id: int, request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    piece = session.get(ContentPiece, piece_id)
    if piece is None or not piece.is_public:
        return RedirectResponse("/explore", status_code=303)
    author = session.get(User, piece.user_id) if piece.user_id else None
    return templates.TemplateResponse(request, "public_piece.html", _ctx(request, piece=piece, author=(author.name or author.email) if author else "Unknown", body_html=_render_markdown(piece.draft), count=_like_count(session, piece.id), liked=_user_liked(session, piece.id, user.id)))


@app.post("/piece/{piece_id}/like", response_class=HTMLResponse)
def toggle_like(piece_id: int, request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request)
    piece = session.get(ContentPiece, piece_id)
    if not user or piece is None or not piece.is_public:
        return HTMLResponse("", status_code=204)
    existing = session.exec(select(PieceLike).where(PieceLike.piece_id == piece_id, PieceLike.user_id == user.id)).first()
    if existing:
        session.delete(existing)
    else:
        session.add(PieceLike(piece_id=piece_id, user_id=user.id))
    session.commit()
    return templates.TemplateResponse(request, "partials/like_button.html", {"piece_id": piece_id, "count": _like_count(session, piece_id), "liked": _user_liked(session, piece_id, user.id)})


@app.post("/piece/{piece_id}/delete")
def delete_piece(piece_id: int, request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request); piece = session.get(ContentPiece, piece_id)
    if user and piece and piece.user_id == user.id:
        session.delete(piece); session.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/piece/{piece_id}/export")
def export_piece(piece_id: int, request: Request, session: Session = Depends(get_session)):
    user = auth.current_user(request); piece = session.get(ContentPiece, piece_id)
    if not user or piece is None or piece.user_id != user.id:
        return RedirectResponse("/", status_code=303)
    front = (f'---\ntitle: "{piece.title}"\ndescription: "{piece.meta_description}"\nslug: {piece.slug}\nkeyword: {piece.keyword}\n---\n\n')
    buf = BytesIO((front + piece.draft).encode("utf-8"))
    return StreamingResponse(buf, media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename={piece.slug or 'content'}.md"})
