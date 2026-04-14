"""
Personalized AI Wealth Copilot — main agent loop.

Usage:
    python agent.py

Requires a .env file with:
    ANTHROPIC_API_KEY, CURRENT_USER_ID, BQ_PROJECT
"""
import json
import os
import sys
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY
from tool_registry import TOOL_HANDLERS
from tool_schemas import TOOL_SCHEMAS

MODEL = "claude-opus-4-6"
MEMORY_FILE = Path(__file__).parent / "memory" / "user_memory.md"
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


def _load_memory() -> str:
    if not MEMORY_FILE.exists():
        return ""
    content = MEMORY_FILE.read_text().strip()
    if not content:
        return ""
    return f"\n\n--- User Profile (learned from past conversations) ---\n{content}\n---"


def _dispatch_tool(tool_name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"})
    try:
        return handler(**tool_input)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def run():
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = []

    print("Wealth Copilot ready. Type your question (or 'quit' to exit).\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        memory_section = _load_memory()
        skill_index = _load_skill_index()
        system = SYSTEM_PROMPT.format(memory_section=memory_section + skill_index)

        # Agentic loop — keep calling until stop_reason is "end_turn"
        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
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
            text_output = []
            tool_results = []

            for block in response.content:
                if block.type == "text":
                    text_output.append(block.text)
                elif block.type == "tool_use":
                    result = _dispatch_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if text_output:
                print(f"\nAssistant: {''.join(text_output)}\n")

            if response.stop_reason == "end_turn":
                # Append assistant response to history (text only for readability)
                assistant_text = "".join(text_output)
                messages.append({"role": "assistant", "content": assistant_text})
                break

            if response.stop_reason == "tool_use":
                # Append full assistant response (with tool_use blocks) then tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                # Loop continues to get Claude's synthesis of the tool results


if __name__ == "__main__":
    run()
