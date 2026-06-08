#!/usr/bin/env python3
"""
SessionStart Hook
==================

Fires when Claude Code starts a new session.
Outputs project context (recent + important memories) to stdout.
Claude sees this as fresh context at session start.

Register in .claude/settings.json (startup/resume/clear, not compaction):
{
    "hooks": {
        "SessionStart": [{
            "matcher": "startup|resume|clear",
            "hooks": [{
                "type": "command",
                "command": "python -m rainman.hooks.session_start"
            }]
        }]
    }
}
"""

import json
import os
import sys


def _emit_context(text: str) -> None:
    """
    Emit context for Claude Code to inject, using the documented
    SessionStart structured output (hookSpecificOutput.additionalContext).
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


def main():
    # Read hook input from stdin
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        print(f"[rainman] session_start: failed to parse input: {e}", file=sys.stderr)
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # Import here to keep startup fast
    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=cwd)
    results = engine.context(limit=8)

    if not results:
        sys.exit(0)

    lines = ["[Rainman] Project memory loaded:\n"]
    for i, r in enumerate(results, 1):
        m = r.memory
        line = f"  {i}. [{m.category}] {m.content[:120]}"
        if m.file_refs:
            line += f" (files: {', '.join(m.file_refs)})"
        lines.append(line)

    lines.append(
        "\nUse the `recall` tool to search for more specific knowledge. "
        "Use `remember` to save new learnings."
    )

    # Structured output — Claude Code injects additionalContext into the session
    _emit_context("\n".join(lines))


if __name__ == "__main__":
    main()
