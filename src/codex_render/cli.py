from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from string import Template
from urllib.parse import quote

import markdown
import nh3
from pygments.formatters import HtmlFormatter


MESSAGE_MARKER = "<!-- CODEX_RENDER_MESSAGES -->"
TOC_MARKER = "<!-- CODEX_RENDER_TOC -->"
ALLOWED_TAGS = {
    "a",
    "abbr",
    "blockquote",
    "br",
    "code",
    "dd",
    "del",
    "div",
    "dl",
    "dt",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "input",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": {"class", "href", "id", "title"},
    "abbr": {"title"},
    "code": {"class"},
    "div": {"class", "id"},
    "img": {"alt", "height", "src", "title", "width"},
    "input": {"checked", "class", "disabled", "type"},
    "li": {"class", "id"},
    "ol": {"class", "start"},
    "span": {"class"},
    "td": {"align"},
    "th": {"align"},
    "ul": {"class"},
}


def render_markdown(source: str) -> str:
    rendered = markdown.markdown(
        source,
        extensions=[
            "pymdownx.extra",
            "pymdownx.highlight",
            "pymdownx.tasklist",
            "pymdownx.tilde",
            "pymdownx.magiclink",
            "pymdownx.arithmatex",
        ],
        extension_configs={
            "pymdownx.arithmatex": {"generic": True},
            "pymdownx.highlight": {
                "guess_lang": False,
                "pygments_lang_class": True,
                "use_pygments": True,
            },
            "pymdownx.tasklist": {"clickable_checkbox": False},
            "pymdownx.tilde": {"subscript": False},
        },
    )
    return nh3.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
    )


def thread_filename(session_id: str) -> str:
    return f"{quote(session_id, safe='._-')}.html"


def new_page(session_id: str) -> str:
    source = files("codex_render").joinpath("template.html").read_text(encoding="utf-8")
    return Template(source).substitute(
        title=html.escape(f"Codex thread {session_id}"),
        session_id=html.escape(session_id),
        pygments_css=HtmlFormatter(style="github-dark").get_style_defs(".highlight"),
        toc=_toc_shell(),
    )


def _toc_shell(entries: str = "") -> str:
    return (
        '<aside class="turn-toc" aria-label="Turn navigation">\n'
        '  <div class="turn-toc-title">Turns</div>\n'
        '  <div class="turn-toc-shortcuts">k previous · j next</div>\n'
        "  <nav>\n"
        "    <ol>\n"
        f"{entries}{TOC_MARKER}\n"
        "    </ol>\n"
        "  </nav>\n"
        "</aside>"
    )


def _turn_preview(rendered_message: str, word_limit: int = 8) -> str:
    plain_text = html.unescape(nh3.clean(rendered_message, tags=set(), attributes={}))
    words = plain_text.split()
    preview = " ".join(words[:word_limit])
    if len(words) > word_limit:
        preview += "…"
    return preview


def _toc_entry(turn_number: int, turn_id: str, preview: str) -> str:
    anchor = html.escape(turn_id, quote=True)
    return (
        f'      <li><a href="#{anchor}">'
        f'<span class="turn-toc-number">Turn {turn_number}</span>'
        f'<span class="turn-toc-preview">{html.escape(preview)}</span>'
        "</a></li>\n"
    )


def update_page(payload: dict[str, object], output_dir: str | None = None) -> Path | None:
    if payload.get("hook_event_name") != "Stop":
        raise ValueError("expected hook_event_name to be 'Stop'")

    values = {}
    for field in ("cwd", "session_id", "turn_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a non-empty string")
        values[field] = value

    message = payload.get("last_assistant_message")
    if message is None:
        return None
    if not isinstance(message, str):
        raise ValueError("last_assistant_message must be a string or null")

    destination = Path(output_dir) if output_dir else Path(values["cwd"]) / ".codex-render"
    if not destination.is_absolute():
        destination = Path(values["cwd"]) / destination
    destination.mkdir(parents=True, exist_ok=True)

    target = destination / thread_filename(values["session_id"])
    page = (
        target.read_text(encoding="utf-8")
        if target.exists()
        else new_page(values["session_id"])
    )
    if page.count(MESSAGE_MARKER) != 1:
        raise ValueError(f"existing page has an invalid message marker: {target}")
    if page.count(TOC_MARKER) != 1:
        raise ValueError(f"existing page has an invalid table-of-contents marker: {target}")
    turn_attribute = f'data-turn-id="{html.escape(values["turn_id"], quote=True)}"'
    turn_marker = f"<!-- CODEX_RENDER_TURN:{quote(values['turn_id'], safe='')} -->"
    if turn_marker in page:
        return target

    turn_number = page.count('class="message"') + 1
    turn_anchor = html.escape(values["turn_id"], quote=True)
    rendered_message = render_markdown(message)
    article = (
        f"{turn_marker}\n"
        f'<article id="{turn_anchor}" class="message" {turn_attribute}>\n'
        '<div class="message-label">Assistant '
        f'<span>{html.escape(values["turn_id"])}</span></div>\n'
        f'<div class="markdown-body">\n{rendered_message}\n</div>\n'
        "</article>\n"
    )
    page = page.replace(MESSAGE_MARKER, article + MESSAGE_MARKER)
    page = page.replace(
        TOC_MARKER,
        _toc_entry(
            turn_number,
            values["turn_id"],
            _turn_preview(rendered_message),
        )
        + TOC_MARKER,
    )
    _atomic_write(target, page)
    return target


def _atomic_write(target: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a Codex Stop hook payload as static HTML."
    )
    parser.add_argument(
        "--output-dir",
        help="output directory; relative paths are resolved from the hook cwd",
    )
    args = parser.parse_args(argv)

    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        update_page(payload, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"codex-render: {error}", file=sys.stderr)
        return 1

    print("{}")
    return 0
