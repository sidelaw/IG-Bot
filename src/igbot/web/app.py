"""Minimal FastAPI review queue — the operator gate.

One server-rendered page lists pending candidates with a preview, source +
author attribution, an editable caption, a brand-overlay toggle, and account
routing checkboxes. Nothing publishes without passing through here. Approve →
Publish runs the candidate through the publish pipeline to its routed accounts.
"""

from __future__ import annotations

import html
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..config import Config
from ..db import Store


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="IG-Bot review queue")

    def store() -> Store:
        return Store(config.db_path)

    # ---------------- pages ----------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, status: str = "pending", msg: str = ""):
        s = store()
        try:
            candidates = s.list_candidates(status or None)
            accounts = s.list_accounts()
            routing = {c["id"]: set(s.routing_for(c["id"])) for c in candidates}
        finally:
            s.close()
        return _render_page(candidates, accounts, routing, status, msg, config)

    @app.get("/media/{candidate_id}")
    def media(candidate_id: int):
        s = store()
        try:
            row = s.get_candidate(candidate_id)
        finally:
            s.close()
        if not row or not row["local_path"] or not Path(row["local_path"]).exists():
            return HTMLResponse("media not found", status_code=404)
        return FileResponse(row["local_path"])

    # ---------------- actions ----------------

    @app.post("/candidates/{candidate_id}/update")
    async def update(candidate_id: int, request: Request,
                     caption: str = Form(""), brand_overlay: str = Form("")):
        form = await request.form()
        selected = form.getlist("accounts")
        s = store()
        try:
            valid = {a["id"] for a in s.list_accounts()}
            unknown = [a for a in selected if a not in valid]
            if unknown:
                return _redirect(f"unknown account(s): {', '.join(unknown)}", status="pending")
            s.update_caption(candidate_id, caption)
            s.set_brand_overlay(candidate_id, bool(brand_overlay))
            s.set_routing(candidate_id, [a for a in selected if a in valid])
        finally:
            s.close()
        return _redirect("saved")

    @app.post("/candidates/{candidate_id}/approve")
    def approve(candidate_id: int):
        s = store()
        try:
            s.set_status(candidate_id, "approved")
        finally:
            s.close()
        return _redirect("approved")

    @app.post("/candidates/{candidate_id}/reject")
    def reject(candidate_id: int):
        s = store()
        try:
            s.set_status(candidate_id, "rejected")
        finally:
            s.close()
        return _redirect("rejected", status="pending")

    @app.post("/candidates/{candidate_id}/publish")
    def publish(candidate_id: int):
        from ..publish.runner import publish_candidate
        from ..publish.instagram import PublishError

        s = store()
        try:
            targets = s.routing_for(candidate_id)
        finally:
            s.close()
        if not targets:
            return _redirect("no accounts routed — assign one first", status="pending")
        results = []
        for acct in targets:
            try:
                media_id = publish_candidate(config, candidate_id, acct)
                results.append(f"{acct}={media_id}")
            except PublishError as exc:
                results.append(f"{acct} ERROR: {exc}")
        return _redirect("publish: " + "; ".join(results), status="approved")

    return app


# ---------------- rendering ----------------

def _redirect(msg: str, status: str = "pending") -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/?status={quote(status)}&msg={quote(msg)}",
                            status_code=303)


_STYLE = """
body{font:15px system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1a1a1a}
header{background:#111;color:#fff;padding:12px 20px;display:flex;gap:16px;align-items:center}
header a{color:#8ab4ff;text-decoration:none;margin-right:10px}
.msg{background:#fffae6;border-bottom:1px solid #ffe28a;padding:8px 20px}
.wrap{max-width:1100px;margin:0 auto;padding:20px}
.card{background:#fff;border:1px solid #e2e4e8;border-radius:10px;padding:16px;margin-bottom:18px;display:grid;grid-template-columns:300px 1fr;gap:18px}
.media img,.media video{width:300px;border-radius:8px;background:#000}
.meta{font-size:13px;color:#555;margin-bottom:8px}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;margin-right:6px}
.ok{background:#e3f6e5;color:#1a7f37}.warn{background:#fdecea;color:#b3261e}
textarea{width:100%;min-height:70px;box-sizing:border-box;padding:8px;font:inherit}
.accts label{display:inline-block;margin-right:12px}
.actions{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
button{padding:7px 14px;border:0;border-radius:6px;cursor:pointer;font:inherit}
.save{background:#0b5fff;color:#fff}.approve{background:#1a7f37;color:#fff}
.reject{background:#888;color:#fff}.publish{background:#b3261e;color:#fff}
"""


def _render_page(candidates, accounts, routing, status, msg, config: Config) -> HTMLResponse:
    e = html.escape
    cards = []
    for c in candidates:
        cid = c["id"]
        if c["media_type"] == "video":
            preview = f'<video src="/media/{cid}" controls muted></video>'
        else:
            preview = f'<img src="/media/{cid}" alt="preview">'

        # eligibility / audio badges
        badges = []
        if c["media_type"] == "video":
            badges.append('<span class="badge %s">%s</span>' % (
                ("ok" if c["reels_eligible"] else "warn"),
                ("Reel-eligible" if c["reels_eligible"] else "feed video (not 9:16/5-90s)")))
            badges.append('<span class="badge %s">%s</span>' % (
                ("ok" if c["has_audio"] else "warn"),
                ("audio" if c["has_audio"] else "SILENT")))
        badge_html = "".join(badges)

        checks = []
        for a in accounts:
            checked = "checked" if a["id"] in routing.get(cid, set()) else ""
            checks.append(
                f'<label><input type="checkbox" name="accounts" value="{e(a["id"])}" '
                f'{checked}> {e(a["id"])}{(" (@"+e(a["username"])+")") if a["username"] else ""}</label>'
            )
        brand_checked = "checked" if c["brand_overlay"] else ""
        caption = e(c["caption"] or c["title"] or "")
        permalink = e(c["permalink"] or "")

        cards.append(f"""
        <div class="card">
          <div class="media">{preview}</div>
          <div>
            <div class="meta">
              <b>#{cid}</b> · {e(c["source"])} · u/{e(c["author"] or "?")} · score {c["score"] or 0}
              · status <b>{e(c["status"])}</b><br>{badge_html}
              <br><a href="{permalink}" target="_blank" rel="noopener">source post ↗</a>
            </div>
            <form method="post" action="/candidates/{cid}/update">
              <textarea name="caption" placeholder="caption">{caption}</textarea>
              <div class="accts" style="margin:8px 0">
                <label><input type="checkbox" name="brand_overlay" value="1" {brand_checked}> brand overlay</label>
                &nbsp;|&nbsp; route to: {"".join(checks) or "<i>no accounts configured</i>"}
              </div>
              <div class="actions">
                <button class="save" type="submit">Save</button>
              </div>
            </form>
            <div class="actions">
              <form method="post" action="/candidates/{cid}/approve"><button class="approve">Approve</button></form>
              <form method="post" action="/candidates/{cid}/reject"><button class="reject">Reject</button></form>
              <form method="post" action="/candidates/{cid}/publish"><button class="publish">Publish</button></form>
            </div>
          </div>
        </div>""")

    msg_html = f'<div class="msg">{e(msg)}</div>' if msg else ""
    body = "".join(cards) or "<p>No candidates in this view.</p>"
    nav = " ".join(
        f'<a href="/?status={st}">{st or "all"}</a>'
        for st in ("pending", "approved", "published", "rejected", "")
    )
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>IG-Bot review</title><style>{_STYLE}</style></head><body>
<header><b>IG-Bot review queue</b><span>mode: {e(config.mode)}</span>
<span>{nav}</span></header>{msg_html}
<div class="wrap"><h2>{e(status or "all")} ({len(candidates)})</h2>{body}</div>
</body></html>"""
    return HTMLResponse(page)
