"""
Shared utilities for reading and updating user_memory.md.

Section parsing convention: each section starts with "## Section Name\n"
and ends at the next "## " heading or EOF. Updates replace only the target section.
"""
import re
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "user_memory.md"


def load_memory() -> str:
    if not MEMORY_FILE.exists():
        return ""
    content = MEMORY_FILE.read_text().strip()
    if not content:
        return ""
    return f"\n\n--- User Profile (learned from past conversations) ---\n{content}\n---"


def _read() -> str:
    return MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""


def _write(content: str) -> None:
    MEMORY_FILE.write_text(content)


def update_section(name: str, new_content: str) -> None:
    """Replace the body of a ## section with new_content (strip trailing newlines, add one blank line after)."""
    text = _read()
    header = f"## {name}\n"
    start = text.find(header)
    if start == -1:
        return  # section not found — don't corrupt the file

    body_start = start + len(header)
    # find next ## heading or end of file
    next_section = re.search(r"^## ", text[body_start:], re.MULTILINE)
    body_end = body_start + next_section.start() if next_section else len(text)

    new_body = new_content.strip("\n") + "\n\n"
    _write(text[:body_start] + new_body + text[body_end:])


def append_observation(text: str) -> None:
    """Append a timestamped line to the Conversation Observations section."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- [{ts}] {text}"

    raw = _read()
    header = "## Conversation Observations\n"
    pos = raw.find(header)
    if pos == -1:
        return

    body_start = pos + len(header)
    next_section = re.search(r"^## ", raw[body_start:], re.MULTILINE)
    body_end = body_start + next_section.start() if next_section else len(raw)

    current_body = raw[body_start:body_end].rstrip("\n")
    new_body = current_body + f"\n{line}\n\n"
    _write(raw[:body_start] + new_body + raw[body_end:])


def set_last_updated(source: str) -> None:
    """Update the _Last updated_ line at the top of the file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    raw = _read()
    updated = re.sub(
        r"_Last updated:.*?_",
        f"_Last updated: {ts} | source: {source}_",
        raw,
        count=1,
    )
    _write(updated)
