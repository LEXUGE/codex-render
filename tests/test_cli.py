from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from codex_render.cli import MESSAGE_MARKER, thread_filename


def payload(cwd: Path, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "session_id": "thr_123",
        "turn_id": "turn_1",
        "cwd": str(cwd),
        "hook_event_name": "Stop",
        "last_assistant_message": "First response",
    }
    data.update(overrides)
    return data


def run_hook(data: object, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codex_render", *arguments],
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=False,
    )


def test_creates_appends_and_deduplicates_turns(tmp_path: Path) -> None:
    first = run_hook(
        payload(
            tmp_path,
            last_assistant_message='First response with `data-turn-id="turn_2"`',
        )
    )
    target = tmp_path / ".codex-render" / "thr_123.html"

    assert first.returncode == 0
    assert first.stdout == "{}\n"
    assert first.stderr == ""
    assert target.exists()

    second = run_hook(
        payload(tmp_path, turn_id="turn_2", last_assistant_message="Second response")
    )
    duplicate = run_hook(
        payload(tmp_path, turn_id="turn_2", last_assistant_message="Do not append")
    )
    page = target.read_text(encoding="utf-8")

    assert second.returncode == duplicate.returncode == 0
    assert page.index("First response") < page.index("Second response")
    assert page.count('<article class="message" data-turn-id="turn_2">') == 1
    assert page.count("<!-- CODEX_RENDER_TURN:turn_2 -->") == 1
    assert "Do not append" not in page
    assert page.count(MESSAGE_MARKER) == 1


def test_renders_markdown_math_and_removes_unsafe_html(tmp_path: Path) -> None:
    message = r"""# Result

| Name | Value |
| --- | ---: |
| answer | 42 |

- [x] complete

Inline $x^2$, \(y^2\), and display math:

$$
E = mc^2
$$

\[
a + b
\]

\begin{align}
x &= 1 \\
y &= 2
\end{align}

```python
print("hello")
```

<script>alert("no")</script>
[unsafe](javascript:alert(1))
"""
    result = run_hook(payload(tmp_path, last_assistant_message=message))
    page = (tmp_path / ".codex-render" / "thr_123.html").read_text(encoding="utf-8")

    assert result.returncode == 0
    assert "<h1>Result</h1>" in page
    assert "<table>" in page
    assert "task-list-item" in page
    assert "language-python" in page
    assert page.count('class="arithmatex"') == 5
    assert "mathjax@4.0.0/tex-svg.js" in page
    assert "<script>alert" not in page
    assert "javascript:alert" not in page


def test_null_message_is_a_successful_noop(tmp_path: Path) -> None:
    result = run_hook(payload(tmp_path, last_assistant_message=None))

    assert result.returncode == 0
    assert result.stdout == "{}\n"
    assert not (tmp_path / ".codex-render").exists()


def test_relative_output_override_uses_hook_cwd(tmp_path: Path) -> None:
    result = run_hook(payload(tmp_path), "--output-dir", "rendered")

    assert result.returncode == 0
    assert (tmp_path / "rendered" / "thr_123.html").exists()


def test_session_id_is_encoded_as_one_filename(tmp_path: Path) -> None:
    session_id = "../../outside/thread"
    result = run_hook(payload(tmp_path, session_id=session_id))
    output = tmp_path / ".codex-render"

    assert result.returncode == 0
    assert thread_filename(session_id) == "..%2F..%2Foutside%2Fthread.html"
    assert [path.name for path in output.iterdir()] == [thread_filename(session_id)]
    assert not (tmp_path.parent / "outside").exists()


def test_invalid_payload_reports_error_without_hook_json(tmp_path: Path) -> None:
    result = run_hook(payload(tmp_path, hook_event_name="SessionEnd"))

    assert result.returncode == 1
    assert result.stdout == ""
    assert "expected hook_event_name" in result.stderr


def test_invalid_existing_page_is_not_overwritten(tmp_path: Path) -> None:
    output = tmp_path / ".codex-render"
    output.mkdir()
    target = output / "thr_123.html"
    target.write_text("user-owned content", encoding="utf-8")

    result = run_hook(payload(tmp_path))

    assert result.returncode == 1
    assert "invalid message marker" in result.stderr
    assert target.read_text(encoding="utf-8") == "user-owned content"
