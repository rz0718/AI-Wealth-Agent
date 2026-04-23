"""
Personalized AI Wealth Copilot — main agent loop.

Usage:
    python agent.py

Requires a .env file with:
    ANTHROPIC_API_KEY, CURRENT_USER_ID, BQ_PROJECT
"""
import json
from datetime import datetime
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY
from memory.memory_manager import append_observation, load_memory, set_last_updated
from tool_registry import TOOL_HANDLERS
from tool_schemas import TOOL_SCHEMAS

LOGS_DIR = Path(__file__).parent / "logs"
_log_file = None


def _setup_log() -> Path:
    global _log_file
    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    _log_file = log_path.open("w", buffering=1)  # line-buffered
    return log_path


def _track(label: str, detail: str = "") -> None:
    if _log_file is None:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts}  [{label}]"
    if detail:
        line += f" {detail}"
    _log_file.write(line + "\n")


def _log_message(role: str, content: str) -> None:
    """Write a labeled multi-line message block to the log."""
    if _log_file is None or not content.strip():
        return
    ts = datetime.now().strftime("%H:%M:%S")
    _log_file.write(f"\n{ts}  [{role}]\n{content}\n{'─' * 60}\n")

MODEL = "claude-sonnet-4-6"
SKILL_INDEX_FILE = Path(__file__).parent / "skills" / "index.md"

SYSTEM_PROMPT = """You are a personalized financial analyst for this user.
You have secure access to their portfolio data (trade history, positions, realized and unrealized P&L)
and live market data (prices, news).

Your job is to provide data-backed, actionable financial insights. Always ground your answers in
real data from the available tools. When explaining portfolio movements, combine the user's positions
with relevant market news for a complete picture.

Be concise, direct, and honest. If data is unavailable or unclear, say so.
{memory_section}"""


def _load_skill_index() -> str:
    if not SKILL_INDEX_FILE.exists():
        return ""
    content = SKILL_INDEX_FILE.read_text().strip()
    if not content:
        return ""
    return f"\n\n--- Expert Frameworks (use load_skill to access full methodology) ---\n{content}\n---"


def _summarize_session(messages: list, client: anthropic.Anthropic) -> None:
    """Extract behavioral signals from the conversation and persist to user_memory.md."""
    if len(messages) < 4:
        return  # not enough content to profile

    # Flatten messages to plain text for the extraction prompt
    transcript_lines = []
    for m in messages:
        role = m["role"].upper()
        content = m["content"]
        if isinstance(content, str):
            transcript_lines.append(f"{role}: {content}")
        # skip tool_use/tool_result blocks — not useful for behavioral profiling

    transcript = "\n".join(transcript_lines)

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=(
                "You are a behavioral profiler for a trading app. "
                "Given a conversation transcript, output ONLY valid JSON with keys: "
                '"asset_interests" (list of asset class strings the user focused on), '
                '"signals" (list of short behavioral signal strings observed in the conversation, max 3). '
                "Be concise. No explanation outside the JSON."
            ),
            messages=[{"role": "user", "content": f"Transcript:\n{transcript}"}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
    except Exception as e:
        _track("memory", f"extraction failed: {e}")
        return

    asset_interests = [a.strip() for a in (data.get("asset_interests") or []) if a.strip()]
    signals = [s.strip() for s in (data.get("signals") or []) if s.strip()]

    obs_parts = []
    if asset_interests:
        obs_parts.append(f"asked about: {', '.join(asset_interests)}")
    if signals:
        obs_parts.append("; ".join(signals))
    if obs_parts:
        append_observation(", ".join(obs_parts))

    set_last_updated("conversation")
    _track("memory", "observation appended from session")


def _dispatch_tool(tool_name: str, tool_input: dict) -> str:
    args_preview = ", ".join(f"{k}={v!r}" for k, v in tool_input.items()) if tool_input else ""
    _track(f"tool → {tool_name}", args_preview)

    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        result = json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"})
    else:
        try:
            result = handler(**tool_input)
        except Exception as e:
            result = json.dumps({"status": "error", "message": str(e)})

    try:
        parsed = json.loads(result)
        count = parsed.get("count", "")
        status = parsed.get("status", "")
        summary = f"status={status}" + (f", count={count}" if count != "" else "")
    except Exception:
        summary = result[:120]
    _track(f"tool ← {tool_name}", summary)
    return result


def run():
    log_path = _setup_log()
    print(f"Logging to {log_path}  (tail -f {log_path} to follow)\n")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = []

    print("Wealth Copilot ready. Type your question (or 'quit' to exit).\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            _summarize_session(messages, client)
            if _log_file:
                _log_file.close()
            break

        if user_input.lower() in ("quit", "exit", "q"):
            _summarize_session(messages, client)
            print("Profile updated. Goodbye.")
            if _log_file:
                _log_file.close()
            break

        if not user_input:
            continue

        _log_message("user", user_input)
        messages.append({"role": "user", "content": user_input})

        memory_section = load_memory()
        skill_index = _load_skill_index()
        system = SYSTEM_PROMPT.format(memory_section=memory_section + skill_index)

        # Agentic loop — keep calling until stop_reason is "end_turn"
        step = 0
        while True:
            step += 1
            _track(f"step {step}", f"calling model ({MODEL})")
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=TOOL_SCHEMAS,
                messages=messages,
            )

            # Collect text for display and tool calls to execute
            _track(f"step {step} done", f"stop_reason={response.stop_reason}, blocks={len(response.content)}")
            text_output = []
            tool_results = []

            for block in response.content:
                if block.type == "thinking":
                    preview = block.thinking[:200].replace("\n", " ")
                    _track("thinking", preview + ("…" if len(block.thinking) > 200 else ""))
                elif block.type == "text":
                    text_output.append(block.text)
                elif block.type == "tool_use":
                    result = _dispatch_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if text_output:
                joined = "".join(text_output)
                print(f"\nAssistant: {joined}\n")
                _log_message("assistant", joined)

            if response.stop_reason == "end_turn":
                assistant_text = "".join(text_output)
                messages.append({"role": "assistant", "content": assistant_text})
                break

            elif response.stop_reason == "tool_use":
                # Append full assistant response (with tool_use blocks) then tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                # Loop continues to get Claude's synthesis of the tool results

            elif response.stop_reason == "max_tokens":
                # Response was cut off — surface it rather than silently re-triggering
                print("\n[Response truncated — output hit the token limit]\n")
                _track("max_tokens", "response truncated, breaking loop")
                assistant_text = "".join(text_output)
                messages.append({"role": "assistant", "content": assistant_text})
                break

            else:
                # Unknown stop reason — log and bail to avoid an infinite loop
                _track("unknown stop_reason", response.stop_reason)
                break


if __name__ == "__main__":
    run()
