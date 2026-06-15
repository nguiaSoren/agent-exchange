#!/usr/bin/env python3
"""
tools/build_replay_viewer.py — AGENT-BUILD
Assembles web/replay/shell.html + web/replay/src/{styles.css,reducer.js,view.js,player.js}
into a single dependency-free HTML file.

Usage
-----
  # Generic viewer (rv-data stays null):
  python tools/build_replay_viewer.py

  # Inlined replay (double-clickable, file://):
  python tools/build_replay_viewer.py --inline data/replays/<f>.replay.json [--out PATH]
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Paths (all relative to the repo root, which we derive from this script's
# location so the script works regardless of cwd).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)

_SHELL = os.path.join(_REPO_ROOT, "web", "replay", "shell.html")
_SRC_DIR = os.path.join(_REPO_ROOT, "web", "replay", "src")
_PUBLIC_DIR = os.path.join(_REPO_ROOT, "web", "public")

_SOURCE_FILES = {
    "@@STYLES@@": os.path.join(_SRC_DIR, "styles.css"),
    "@@REDUCER@@": os.path.join(_SRC_DIR, "reducer.js"),
    "@@VIEW@@": os.path.join(_SRC_DIR, "view.js"),
    "@@PLAYER@@": os.path.join(_SRC_DIR, "player.js"),
}

# Map slot → the HTML wrapper to use when inserting the file's content.
_SLOT_WRAPPERS = {
    "@@STYLES@@": ("<style>", "</style>"),
    "@@REDUCER@@": ("<script>", "</script>"),
    "@@VIEW@@": ("<script>", "</script>"),
    "@@PLAYER@@": ("<script>", "</script>"),
}

# Comment form that appears in shell.html
def _slot_comment(slot: str) -> str:
    return f"<!-- {slot} -->"


def _read_file(path: str, label: str) -> str:
    """Read a file or die with a clear error message."""
    if not os.path.isfile(path):
        sys.exit(f"ERROR: {label} not found at {path!r}")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _assert_exactly_one(html: str, slot: str) -> None:
    """Assert the slot comment appears exactly once in the shell HTML."""
    comment = _slot_comment(slot)
    count = html.count(comment)
    if count == 0:
        sys.exit(
            f"ERROR: slot {slot!r} not found in shell.html — "
            f"expected exactly one occurrence of {comment!r}"
        )
    if count > 1:
        sys.exit(
            f"ERROR: slot {slot!r} appears {count} times in shell.html — "
            f"expected exactly one occurrence"
        )


def _replace_slot(html: str, slot: str, content: str) -> str:
    """Replace <!-- @@SLOT@@ --> with the wrapped content."""
    open_tag, close_tag = _SLOT_WRAPPERS[slot]
    replacement = f"{open_tag}\n{content}\n{close_tag}"
    comment = _slot_comment(slot)
    return html.replace(comment, replacement, 1)


def _inline_json_safe(data: object) -> str:
    """
    Serialize *data* to a JSON string that is safe to embed inside a
    <script> tag.  Specifically, the sequence </  is escaped to <\/
    so that </script> (and any variant) inside string values cannot
    prematurely close the enclosing script element.
    """
    raw = json.dumps(data, ensure_ascii=False)
    # Neutralise any </script or </Script etc. that might appear in
    # string values by escaping the forward-slash immediately after <.
    safe = raw.replace("</", "<\\/")
    return safe


# Regex that matches the rv-data script element with body = null.
# Deliberately loose on whitespace / attribute order so it stays robust
# even if the player engineer tweaks formatting slightly.
_RV_DATA_RE = re.compile(
    r'(<script\b[^>]*\bid=["\']rv-data["\'][^>]*>)\s*null\s*(</script>)',
    re.IGNORECASE,
)


def _inject_replay(html: str, replay: object) -> str:
    """Replace the rv-data null body with the serialised replay JSON."""
    matches = _RV_DATA_RE.findall(html)
    if len(matches) == 0:
        sys.exit(
            "ERROR: could not find <script id=\"rv-data\" ...>null</script> in the "
            "assembled HTML.  Check that shell.html contains exactly that element."
        )
    if len(matches) > 1:
        sys.exit(
            f"ERROR: found {len(matches)} matches for the rv-data slot — expected exactly 1."
        )
    safe_json = _inline_json_safe(replay)
    # Replace using the regex so we're not sensitive to exact whitespace.
    result = _RV_DATA_RE.sub(
        lambda m: m.group(1) + safe_json + m.group(2),
        html,
        count=1,
    )
    return result


def assemble(
    shell_html: str,
    source_contents: dict,  # slot → raw file content
) -> str:
    """
    Validate all slots exist exactly once then replace them in order.
    Returns the fully assembled HTML string.
    """
    for slot in _SOURCE_FILES:
        _assert_exactly_one(shell_html, slot)

    html = shell_html
    for slot, content in source_contents.items():
        html = _replace_slot(html, slot, content)

    return html


def build(inline_path: str | None = None, out_path: str | None = None) -> str:
    """
    Core build routine.

    Parameters
    ----------
    inline_path : str | None
        Path to a .replay.json file to inline.  None → generic viewer.
    out_path : str | None
        Explicit output path.  None → derive from job_id (inline) or
        use the fixed generic name.

    Returns
    -------
    str  — the output file path that was written.
    """
    # 1. Read shell
    shell_html = _read_file(_SHELL, "shell.html")

    # 2. Read source files
    source_contents: dict[str, str] = {}
    for slot, src_path in _SOURCE_FILES.items():
        label = os.path.basename(src_path)
        source_contents[slot] = _read_file(src_path, label)

    # 3. Assemble (slot replacement)
    html = assemble(shell_html, source_contents)

    # 4. Optionally inline a replay
    if inline_path is not None:
        if not os.path.isfile(inline_path):
            sys.exit(f"ERROR: replay file not found at {inline_path!r}")
        with open(inline_path, "r", encoding="utf-8") as fh:
            replay = json.load(fh)
        html = _inject_replay(html, replay)
        job_id = replay.get("job_id", "unknown")
    else:
        job_id = None

    # 5. Verify no residual @@ markers remain
    residuals = re.findall(r"@@\w+@@", html)
    if residuals:
        sys.exit(
            f"ERROR: assembled HTML still contains residual slot marker(s): "
            f"{residuals}.  This is a bug in the assembler."
        )

    # 6. If inlined, assert the job_id is present in the output
    if job_id is not None:
        if job_id not in html:
            sys.exit(
                f"ERROR: job_id {job_id!r} not found in assembled output — "
                f"inline injection appears to have failed."
            )

    # 7. Determine output path
    if out_path is None:
        os.makedirs(_PUBLIC_DIR, exist_ok=True)
        if job_id is not None:
            out_path = os.path.join(_PUBLIC_DIR, f"replay-{job_id}.html")
        else:
            out_path = os.path.join(_PUBLIC_DIR, "replay_viewer.html")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # 8. Write output
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    byte_size = os.path.getsize(out_path)
    print(f"Written: {out_path}  ({byte_size:,} bytes)")
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble the Agent-Exchange replay viewer HTML.\n\n"
            "Without --inline: writes web/public/replay_viewer.html (generic loader).\n"
            "With --inline:    inlines a replay JSON into a double-clickable HTML file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--inline",
        metavar="REPLAY_JSON",
        default=None,
        help=(
            "Path to a .replay.json file to bake into the output. "
            "Default output: web/public/replay-<job_id>.html"
        ),
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Explicit output path (overrides the default derivation).",
    )
    args = parser.parse_args()
    build(inline_path=args.inline, out_path=args.out)


if __name__ == "__main__":
    main()
