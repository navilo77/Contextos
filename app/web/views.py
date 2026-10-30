from __future__ import annotations

import html
import json

from fastapi import Request
from fastapi.responses import HTMLResponse

from app.models import GeneratedDocuments
from app.session_store import Session

MAX_IDEA_CHARS = 20_000

STYLE = """
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#17201d;background:#f5f7f4}
body{margin:0}.wrap{max-width:850px;margin:40px auto;padding:0 20px}
header,.card{background:#fff;border:1px solid #dce4dd;border-radius:14px;padding:24px;margin:16px 0}
h1{margin-top:0;color:#176349}h2{margin-top:0}p,li{line-height:1.55}
label{display:block;font-weight:650;margin:16px 0 6px}
input[type=text],textarea,select{box-sizing:border-box;width:100%;padding:11px;border:1px solid #aebbb0;border-radius:8px;font:inherit}
textarea{min-height:110px}button,.button{display:inline-block;background:#176349;color:white;border:0;border-radius:8px;padding:12px 18px;font:inherit;font-weight:650;cursor:pointer;text-decoration:none}
.secondary{background:#e9efea;color:#173c2e}.notice{background:#edf6f0;padding:14px;border-radius:8px}
.error{background:#fff0ed;color:#802313;padding:14px;border-radius:8px}.muted{color:#536259;font-size:.95rem}
.question{border-top:1px solid #e3e8e4;padding:14px 0}.inline{display:flex;gap:10px;align-items:center}.inline label{display:inline;margin:0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f4;padding:16px;border-radius:8px;font:inherit;font-size:.92rem}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}
</style>
"""


def page(title: str, content: str, status: int = 200) -> HTMLResponse:
    safe_title = html.escape(title)
    document = (
        '<!doctype html><html lang="bn"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{safe_title} — Context OS</title>{STYLE}</head>"
        f'<body><main class="wrap"><header><h1>Context OS</h1>'
        '<p class="muted">তোমার app idea-কে coding agent-এর জন্য পরিষ্কার project context-এ রূপান্তর করো।</p>'
        f"</header>{content}</main></body></html>"
    )
    return HTMLResponse(document, status_code=status)


def home_content(csrf: str, old: dict[str, str]) -> str:
    def val(key: str) -> str:
        return html.escape(str(old.get(key, "")), quote=True)

    selected_compact = "selected" if old.get("profile", "compact") == "compact" else ""
    selected_detailed = "selected" if old.get("profile") == "detailed" else ""
    language = old.get("language", "auto")
    options = "".join(
        f'<option value="{value}" {"selected" if language == value else ""}>{label}</option>'
        for value, label in [
            ("auto", "Idea যে ভাষায়, সেই ভাষায়"),
            ("বাংলা", "বাংলা"),
            ("English", "English"),
        ]
    )
    return (
        '<section class="card"><h2>তোমার app idea</h2>'
        "<p>এখানে Context OS শুধু documentation ও coding-agent context ZIP বানাবে; app-এর code নিজে লিখবে না।</p>"
        '<form method="post" action="/clarify">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(csrf, quote=True)}">'
        f'<label for="idea">Idea * (সর্বোচ্চ ২০,০০০ অক্ষর)</label><textarea id="idea" name="idea" maxlength="{MAX_IDEA_CHARS}" required>{val("idea")}</textarea>'
        f'<label for="audience">কারা ব্যবহার করবে? (জানা থাকলে)</label><input id="audience" name="audience" maxlength="1000" value="{val("audience")}">'
        f'<label for="platform">কোন platform? (জানা থাকলে)</label><input id="platform" name="platform" maxlength="500" value="{val("platform")}" placeholder="Web, mobile, desktop...">'
        f'<label for="constraints">কোনো সীমাবদ্ধতা বা কী করবে না? (জানা থাকলে)</label><textarea id="constraints" name="constraints" maxlength="2000">{val("constraints")}</textarea>'
        f'<label for="technology">পছন্দের technology (জানা থাকলে)</label><input id="technology" name="technology" maxlength="500" value="{val("technology")}">'
        f'<label for="language">Output ভাষা</label><select id="language" name="language">{options}</select>'
        f'<label for="profile">Package-এর detail</label><select id="profile" name="profile">'
        f'<option value="compact" {selected_compact}>Compact</option><option value="detailed" {selected_detailed}>Detailed</option></select>'
        '<p class="notice"><strong>গোপনীয়তা:</strong> পরের ধাপে idea ও উত্তর তোমার configure করা বাহ্যিক AI provider-এ পাঠানো হবে। '
        "Context OS সেগুলো নিজের disk-এ সংরক্ষণ করে না; session process memory-তে সর্বোচ্চ ৩০ মিনিট থাকে। "
        "ZIP-এর secret scan সম্পূর্ণ নিশ্চয়তা নয়—download-এর পর নিজে দেখে নিও।</p>"
        '<div class="inline"><input id="consent" type="checkbox" name="consent" value="yes" required>'
        '<label for="consent">আমি বুঝেছি, আমার idea configure করা AI provider-এ পাঠানো হবে।</label></div>'
        '<p><button type="submit">Idea বুঝে প্রশ্ন করো</button></p></form></section>'
        '<form method="post" action="/reset"><input type="hidden" name="csrf_token" value="'
        + html.escape(csrf, quote=True)
        + '"><button class="secondary" type="submit">Session মুছে নতুন করে শুরু</button></form>'
    )


def questions_content(session: Session) -> str:
    questions = session.data["questions"]
    saved_answers = session.data.get("answers", {})
    parts = [
        '<section class="card"><h2>তোমার idea-র জন্য প্রশ্ন</h2>'
        "<p>উত্তর না জানলে ফাঁকা রাখো বা ‘এখনো ঠিক করিনি’ বেছে নাও; agent অনুমান করে এটাকে fact বানাবে না।</p>"
        '<form method="post" action="/review">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}">'
    ]
    if not questions:
        parts.append(
            '<p class="notice">এই মুহূর্তে জরুরি clarification question নেই। পরের ধাপে review তৈরি হবে।</p>'
        )
    for index, question in enumerate(questions):
        label = html.escape(question["question"])
        impact = html.escape(question["impact"])
        saved_answer = saved_answers.get(question["question"], "")
        is_unknown = saved_answer == "Not decided yet."
        answer_value = "" if is_unknown else saved_answer
        parts.append(
            f'<div class="question"><label for="answer_{index}">{index + 1}. {label}</label>'
            f'<p class="muted">কেন জিজ্ঞেস করছি: {impact} · '
            f"{'Blocking' if question['blocking'] else 'ঐচ্ছিক'}</p>"
            f'<textarea id="answer_{index}" name="answer_{index}" maxlength="2000">{html.escape(answer_value)}</textarea>'
            f'<div class="inline"><input id="unknown_{index}" type="checkbox" name="unknown_{index}" value="yes" {"checked" if is_unknown else ""}>'
            f'<label for="unknown_{index}">এখনো ঠিক করিনি</label></div></div>'
        )
    parts.append(
        '<div class="actions"><button type="submit">উত্তর review করে documents বানাও</button></div></form>'
        + back_form(session.csrf_token)
        + "</section>"
    )
    return "".join(parts)


def preview_content(session: Session) -> str:
    generated = GeneratedDocuments.model_validate(session.data["generated"])
    package = session.data["package"]
    context = json.loads(package["context/project-context.json"])
    preview_paths = [
        "00-project/PROJECT_BRIEF.md",
        "01-product/REQUIREMENTS.md",
        "01-product/IMPLEMENTATION_PLAN.md",
        "context/OPEN_QUESTIONS.md",
    ]
    sections = []
    for path in preview_paths:
        sections.append(
            f"<details><summary>{html.escape(path)}</summary><pre>"
            f"{html.escape(package[path].decode('utf-8'))}</pre></details>"
        )
    uncertainty = []
    for heading, field in (
        ("নিশ্চিত তথ্য", "facts"),
        ("গৃহীত প্রস্তাব", "accepted_proposals"),
        ("অনুমান", "assumptions"),
    ):
        items = context[field]
        values = "".join(
            f'<li>{html.escape(item["text"])} <span class="muted">(source: {html.escape(item["source"])})</span></li>'
            for item in items
        )
        uncertainty.append(f"<h3>{heading}</h3><ul>{values or '<li>কিছু উল্লেখ নেই।</li>'}</ul>")
    questions = "".join(
        f"<li>{html.escape(item['question'])} — {html.escape(item['impact'])} "
        f"(blocking: {'হ্যাঁ' if item['blocking'] else 'না'})</li>"
        for item in context["open_questions"]
    )
    file_list = "".join(f"<li>{html.escape(path)}</li>" for path in sorted(package))
    return (
        '<section class="card"><h2>ZIP তৈরির আগে review</h2>'
        f"<p><strong>Project:</strong> {html.escape(generated.project_name)}</p>"
        f"<p><strong>Profile:</strong> {html.escape(session.data['intake']['profile'])}</p>"
        '<p class="notice">ZIP তৈরি ও যাচাই করা হয়েছে। এটি specification package—app code নয়। '
        "Secret scanning সম্পূর্ণ নিশ্চয়তা দেয় না।</p>"
        "<h3>তথ্য ও অনিশ্চয়তা review</h3>"
        + "".join(uncertainty)
        + "<h3>এখনো খোলা প্রশ্ন</h3><ul>"
        + (questions or "<li>খোলা প্রশ্ন নেই।</li>")
        + "</ul>"
        + "<h3>Documents-এর preview</h3>"
        + "".join(sections)
        + "<h3>ZIP-এ থাকা ফাইল</h3><ul>"
        + file_list
        + "</ul>"
        '<div class="actions"><form method="post" action="/download">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}">'
        '<button type="submit">ZIP download</button></form>'
        '<form method="post" action="/edit">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}">'
        '<button class="secondary" type="submit">উত্তর edit করো</button></form>'
        '<form method="post" action="/edit-idea">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token, quote=True)}">'
        '<button class="secondary" type="submit">Idea edit করো</button></form></div>'
        + back_form(session.csrf_token)
        + "</section>"
    )


def back_form(csrf: str) -> str:
    return (
        '<form method="post" action="/reset"><input type="hidden" name="csrf_token" value="'
        + html.escape(csrf, quote=True)
        + '"><button class="secondary" type="submit">Discard / নতুন idea</button></form>'
    )


def error_page(request: Request, message: str, status: int = 400) -> HTMLResponse:
    safe_message = html.escape(message)
    content = (
        f'<section class="card"><div class="error"><strong>কাজটি করা যায়নি:</strong> {safe_message}</div>'
        '<p><a class="button secondary" href="/">ফিরে যাও</a></p></section>'
    )
    return page("একটি সমস্যা হয়েছে", content, status=status)
