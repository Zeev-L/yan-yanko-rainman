#!/usr/bin/env python3
"""
Post-Compaction Re-Injection Hook — The Killer Feature
======================================================

Runs right after Claude Code compacts context (long sessions).
This is EXACTLY when memories get lost.

Claude Code has no "PostCompact" event — instead it fires `SessionStart`
with source "compact" once compaction completes. So this hook is wired to
SessionStart with matcher "compact". It reads the event, extracts the current
working topic, recalls relevant memories, and outputs them to stdout for
re-injection into Claude's context.

Register in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "compact",
            "hooks": [{
                "type": "command",
                "command": "python -m rainman.hooks.post_compact"
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
    This hook runs on SessionStart with source "compact".
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


def main():
    # Read compaction event from stdin
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        print(f"[rainman] post_compact: failed to parse input: {e}", file=sys.stderr)
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # Try to extract working topic from the compaction summary
    summary = hook_input.get("summary", "")
    transcript = hook_input.get("transcript_snippet", "")

    # Build a search query from available context
    query_parts = []
    if summary:
        # Take key words from summary
        query_parts.append(summary[:200])
    if transcript:
        query_parts.append(transcript[:200])

    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=cwd)

    lines = ["[Rainman] Re-injecting project memory after context compaction:\n"]

    if query_parts:
        # Recall by topic
        query = " ".join(query_parts)
        results = engine.recall(query, limit=5)
        if results:
            lines.append("Relevant to current work:")
            for i, r in enumerate(results, 1):
                m = r.memory
                line = f"  {i}. [{m.category}] {m.content[:150]}"
                if m.file_refs:
                    line += f"\n     files: {', '.join(m.file_refs)}"
                lines.append(line)
            lines.append("")

    # Always include high-importance context regardless of topic
    context = engine.context(limit=5)
    if context:
        lines.append("High-importance project knowledge:")
        for i, r in enumerate(context, 1):
            m = r.memory
            # Skip if already included above
            line = f"  {i}. [{m.category}] {m.content[:150]}"
            if m.file_refs:
                line += f"\n     files: {', '.join(m.file_refs)}"
            lines.append(line)

    lines.append(
        "\nUse `recall` to search for specific knowledge. "
        "Use `remember` to save important learnings before next compaction."
    )

    _emit_context("\n".join(lines))


if __name__ == "__main__":
    main()
