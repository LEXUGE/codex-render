# codex-render

`codex-render` is a small [Codex Stop hook](https://learn.chatgpt.com/codex/hooks)
that appends each assistant response to a static HTML page. It renders Markdown,
syntax-highlighted code, and TeX math that the terminal UI cannot display.

Each Codex session writes to:

```text
<session cwd>/.codex-render/<session_id>.html
```

The page uses MathJax from jsDelivr, so math typesetting requires network access
when the file is opened. Refresh the browser manually after a new response.

## Install

The recommended installation uses `uv`, which provides an isolated environment
and can provision Python on systems such as NixOS:

```sh
git clone <repository-url>
cd codex-render
uv tool install --python 3.12 .
```

If `uv` warns that its executable directory is not on `PATH`, run:

```sh
uv tool update-shell
```

`uv tool dir --bin` prints the directory containing the installed
`codex-render` executable. Restart Codex after changing `PATH`.

## Configure the Stop hook

This repository already includes `.codex/hooks.json`. In a trusted checkout it
runs the locked project environment with `uv run --frozen`; open `/hooks` in
Codex CLI to review and trust it.

Add this to `~/.codex/hooks.json` to enable rendering in every Codex project:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "codex-render",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Open `/hooks` in Codex CLI to review and trust the new hook. Codex skips
untrusted command hooks.

To write pages somewhere else, pass an absolute path or a path relative to the
session working directory:

```json
"command": "codex-render --output-dir rendered-codex"
```

For development without installing the tool, point the hook at this checkout:

```json
"command": "uv run --project /absolute/path/to/codex-render codex-render"
```

## Development

Install the locked development environment and run the tests:

```sh
uv sync --frozen
uv run pytest
```

The hook reads one JSON object from standard input. A manual smoke test looks
like this:

```sh
printf '%s' '{"session_id":"thr_demo","turn_id":"turn_1","cwd":"/tmp","hook_event_name":"Stop","last_assistant_message":"Euler: $e^{i\\pi}+1=0$"}' \
  | uv run codex-render
```

On success it writes the page and prints `{}` for Codex. A null
`last_assistant_message` is a successful no-op. Existing responses are keyed by
`turn_id`, so replaying the same Stop event does not append it twice.
