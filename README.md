# Rainman

[![CI](https://github.com/Zeev-L/yan-yanko-rainman/actions/workflows/ci.yml/badge.svg)](https://github.com/Zeev-L/yan-yanko-rainman/actions/workflows/ci.yml)

**Context-aware project memory for AI coding tools.** Rainman remembers what you've built, what failed, and what works — then surfaces the right knowledge to your AI assistant *at the moment it's needed*, without being asked.

> **Zero LLM. Zero tokens. Zero external dependencies. 100% local.**

Rainman is a small Python package (stdlib only) that plugs into AI coding workflows through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io) and [Claude Code](https://docs.claude.com/en/docs/claude-code) lifecycle hooks. All retrieval is keyword matching plus math — no embeddings, no API calls, no tokens consumed.

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [Validated Results](#validated-results)
- [Quick Start](#quick-start)
- [Claude Code Integration](#claude-code-integration)
- [How It Works](#how-it-works)
- [Data Model](#data-model)
- [CLI Reference](#cli-reference)
- [MCP Tools](#mcp-tools)
- [Repository Layout](#repository-layout)
- [Development](#development)
- [Design Rules](#design-rules)
- [Origin](#origin)
- [Requirements & License](#requirements--license)

---

## Why This Exists

We were debugging a systematic voting bias in an election predictor. The AI assistant (Claude Code) declared the problem *"unfixable by prompt engineering"* and spent hours exploring workarounds.

The fix already existed in the codebase — a 516-line, science-grounded module (`political_identity.py`) that assigns party ID using ANES/Pew data without any LLM calls. It had been built weeks earlier. **The AI forgot it existed.**

This wasn't a one-off. Despite a 500+ line `CLAUDE.md`, dedicated memory files, and full codebase access, the AI couldn't connect *"election bias problem"* to *"existing solution in the codebase."* Static documentation describes what things **are** — it doesn't **activate** when relevant.

Rainman fixes this. It is a persistent memory layer with *contextual retrieval*: knowledge is scored and surfaced based on what you're currently working on, and re-injected automatically when the AI's context is lost to compaction.

## Validated Results

Tested on the same codebase where the problem was discovered (307 memories ingested from git history + file structure + manual learnings):

| Query | #1 Result | Score |
|-------|-----------|-------|
| `election voting bias` | `political_identity.py` — the exact forgotten module | **0.937** |
| `political identity assignment` | RLHF bias failure + `political_identity.py` | **0.970** |
| `CEP migrate claude sonnet` | CEP calibration warning (DO NOT migrate without re-validation) | **0.891** |
| `cognitrait personality memory` | CogniTrait description + related engine files | **0.867** |

The module that was "unfindable" now surfaces as the **#1 result** in every relevant query.

## Quick Start

```bash
# Install straight from GitHub (no PyPI required)
pip install git+https://github.com/Zeev-L/yan-yanko-rainman.git

# Initialize .rainman/ in your project
cd /your/project
rainman init

# Seed memory from existing project knowledge
rainman ingest --git --files

# Add memories manually
rainman add "The auth module uses JWT with 30-day expiry" -c pattern -f api/auth.py
rainman add "Fixed: OOM on Railway caused by unbounded asyncio.gather" -c solution

# Search
rainman recall "authentication"
rainman recall "memory leak" -c failure

# Inspect what Rainman knows
rainman status
rainman context
```

**One-command onboarding** wires up everything (`.rainman/` + MCP registration + Claude Code hooks):

```bash
rainman setup
```

And a built-in self-test verifies the engine, storage, and integrations:

```bash
rainman doctor
```

## Claude Code Integration

### MCP Server (recommended)

Register Rainman as an MCP tool provider. Claude gains 5 tools: `recall`, `remember`, `context`, `links`, `status`.

```bash
claude mcp add rainman -- python -m rainman serve
```

Or add it to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "rainman": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "rainman", "serve"]
    }
  }
}
```

### Lifecycle Hooks

Add to `.claude/settings.json` for fully automatic memory management (or just run `rainman setup`, which writes this for you):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear",
        "hooks": [{ "type": "command", "command": "python -m rainman.hooks.session_start" }]
      },
      {
        "matcher": "compact",
        "hooks": [{ "type": "command", "command": "python -m rainman.hooks.post_compact" }]
      }
    ],
    "PostToolUse": [{
      "matcher": "",
      "hooks": [{ "type": "command", "command": "python -m rainman.hooks.post_tool_use" }]
    }]
  }
}
```

| Event (matcher) | Script | What It Does |
|-----------------|--------|--------------|
| `SessionStart` (`startup\|resume\|clear`) | `session_start` | Loads project context so Claude starts knowing what exists |
| `SessionStart` (`compact`) | `post_compact` | Re-injects relevant memories after a context compaction — **the killer feature** |
| `PostToolUse` | `post_tool_use` | Auto-learns from file reads, edits, and test runs |

> **Why the compaction hook matters most.** During long sessions Claude's context gets compacted and earlier knowledge is dropped. Claude Code has no dedicated "post-compact" event — instead it re-fires `SessionStart` with source `compact` once compaction completes, which is exactly when this hook recalls the relevant memories and re-injects them into the fresh context — so the assistant doesn't "forget" mid-task.

## How It Works

### Composite Scoring

Every memory receives a weighted composite score on recall. Weights are **fixed** (no LLM, no tuning loop):

| Component | Weight | What It Does |
|-----------|--------|--------------|
| **Keyword** | 0.35 | Semantic-aware term overlap across content + tags + file refs, with a rehearsal boost |
| **Recency** | 0.25 | ACT-R power-law decay, **14-day half-life**, reset on each access |
| **Importance** | 0.20 | Category-based (failure 0.9, solution 0.8, decision 0.7…) plus keyword boost |
| **Associative** | 0.20 | Boost from being linked to other high-scoring memories |

### Semantic Matching (no embeddings, no LLM)

The keyword component is more than literal string matching. Each query term is matched against memory tokens by the best of three strategies, all pure stdlib:

1. **Exact match** — same token.
2. **Stem match** — plural/verb forms collapse together (`tokens`↔`token`, `migrations`↔`migrate`).
3. **Synonym group** — a curated, domain-aware map links paraphrases (`electoral skew` ↔ `voting bias`, `db` ↔ `database`, `auth` ↔ `authentication`).

Tokenization strips punctuation and stopwords, so `"Fixed the bug."` matches a query for `bug`. Synonym matches are weighted slightly below exact/stem matches to preserve precision — unrelated terms still score zero. This closes the biggest gap of naive keyword retrieval (missing semantically-equivalent phrasings) without giving up the zero-cost, fully-local design. See [`rainman/core/text.py`](rainman/core/text.py).

### Two-Phase Retrieval

1. Score every memory **without** the associative boost → find the top-K anchors.
2. Re-score **with** the associative boost using those anchors → linked knowledge surfaces.

So recalling a memory about *"voting bias"* also boosts related memories about *"RLHF"*, *"political identity"*, and *"election predictor"* — even when they don't directly match the query text.

### Layered Storage

```
~/.rainman/              Global layer  — cross-project learnings
  memories.json
  config.json

<project>/.rainman/      Project layer — git-committable, team-shareable
  memories.json
  config.json
```

Both layers merge on recall, and **project memories get a 1.2× relevance boost** over global ones. Writes are atomic (temp file + `os.replace`) to prevent corruption on crash.

### Memory Categories

| Category | Importance | Use For |
|----------|-----------|---------|
| `failure` | 0.9 | Bugs, regressions, things that broke |
| `solution` | 0.8 | Fixes, workarounds, things that worked |
| `decision` | 0.7 | Architecture choices, trade-offs, "why we did X" |
| `pattern` | 0.6 | Recurring patterns and idioms |
| `convention` | 0.5 | Style rules, naming conventions |
| `note` | 0.4 | General observations, file descriptions |

### Auto-Linking

New memories automatically link to existing ones when keyword overlap is **≥ 25%**, building the associative graph that powers phase-2 retrieval.

### Auto-Sentiment

Every memory is classified by a keyword-based sentiment model (zero LLM) into one of six labels: `positive`, `negative`, `neutral`, `anxious`, `frustrated`, `excited`. Developer-specific terms are baked in (`regression`/`workaround`/`hack` → frustrated; `deployed`/`shipped`/`works` → positive).

### Auto-Pruning

The store caps at **2000 memories**. When exceeded, the lowest-importance and oldest entries are dropped first.

## Data Model

```python
@dataclass
class Memory:
    id: str                      # timestamp + random hex
    content: str                 # the knowledge itself
    timestamp: float             # creation time
    importance: float            # 0–1, auto-calculated from category + keywords
    category: str                # pattern | solution | failure | decision | convention | note
    sentiment: str               # positive | negative | neutral | anxious | frustrated | excited
    linked_ids: list[str]        # associative graph edges (auto-linked by keyword overlap)
    recall_count: int            # rehearsal count (ACT-R)
    last_recalled: float | None  # last access time
    tags: list[str]              # user-defined tags
    source: str                  # "git:abc123" | "cli" | "mcp" | "hook:post_tool_use" | "ingest:files"
    file_refs: list[str]         # files this memory relates to
    layer: str                   # "project" | "global"
    metadata: dict
```

`recall()` returns `RecallResult` objects that carry the full score breakdown (`total`, `keyword`, `recency`, `importance`, `associative`) so you can see *why* a memory ranked where it did.

## CLI Reference

```
rainman init [--dir PATH]                 Initialize .rainman/ in a directory
rainman add "content" [options]           Add a memory
  -c, --category {pattern,solution,failure,decision,convention,note}
  -t, --tag TAG                           Add tag (repeatable)
  -f, --file PATH                         Add file reference (repeatable)
  --global                                Store in the global layer
rainman recall "query" [options]          Search memories
  -n, --limit N                           Max results (default: 5)
  -c, --category CATEGORY                 Filter by category
rainman status                            Memory statistics
rainman links <ref>                       Memories linked to a file/concept
rainman context [-n LIMIT]                Current working context (no query needed)
rainman ingest [options]                  Seed memory from project history
  --git                                   Parse git log into memories
  --files                                 Scan file structure into memories
  -n, --limit N                           Max git commits (default: 50)
  --depth N                               Max directory depth (default: 4)
rainman export                            Dump all memories as JSON
rainman setup                             One-command: init + MCP + hooks
rainman doctor                            Self-test engine, storage, integrations
rainman serve                             Start the MCP stdio server
```

> `context` needs no query — it returns a blend of **60% most-recent + 40% highest-importance** memories, ideal for session bootstrap.

## MCP Tools

When running `rainman serve`, the assistant gets these five tools over JSON-RPC 2.0 (stdio):

| Tool | Description |
|------|-------------|
| `recall` | Search memories — *call this before declaring a problem unsolvable* |
| `remember` | Store a new learning |
| `context` | Get the current working context |
| `links` | Show memories linked to a file or concept |
| `status` | Memory statistics |

## Repository Layout

```
rainman/                  Python package (the core product)
  core/
    models.py             Memory + RecallResult dataclasses
    scoring.py            Keyword, temporal decay, importance, associative scoring
    sentiment.py          Keyword-based sentiment classifier (zero LLM)
    engine.py             add · recall · context · links · forget · persist
    store.py              Layered JSON persistence (global + project)
  mcp/
    server.py             MCP stdio server (JSON-RPC 2.0, 5 tools)
  cli/
    commands.py           CLI command implementations
  hooks/
    session_start.py      Load project context at session start
    post_compact.py       Re-inject memories after context compaction
    post_tool_use.py      Auto-learn from file reads, edits, test runs
  ingest/
    git.py                Parse git log into memories
    files.py              Scan the project file tree into memories
  __main__.py             CLI entry point (argparse)

tests/                    137 tests, <1s, stdlib unittest/pytest
landing/                  Marketing site (Vite + React + Tailwind)
demo-video/               Programmatic demo video (Remotion)
docs/, site/              Built/static site assets
.github/workflows/ci.yml  CI pipeline
CLAUDE.md                 Project instructions for AI assistants
```

## Development

```bash
# Clone
git clone https://github.com/Zeev-L/yan-yanko-rainman.git
cd yan-yanko-rainman

# Install in editable mode (only setuptools is needed)
pip install -e .

# Run the test suite (fast — under a second)
pytest tests/                 # all 137 tests
pytest tests/ -m unit         # unit tests only

# Self-check the install end-to-end
rainman doctor
```

**Test breakdown:** engine (25), scoring (22), MCP server (19), integration (14), hooks (13), semantic recall (13), regressions (12), sentiment (10), CLI smoke (9).

The `landing/` and `demo-video/` sub-projects are independent Node/Vite workspaces with their own `package.json`; they are not required to use or develop the core Python package.

## Design Rules

These are hard constraints — keep them intact in any contribution:

- **Zero external dependencies.** stdlib only; nothing beyond setuptools to install.
- **Zero LLM calls.** All scoring is keyword matching + math. No tokens consumed, ever.
- **Atomic writes.** The store uses temp file + `os.replace` to survive crashes.
- **Don't break the tests.** Run the suite before any change.
- **Auto-link threshold = 0.25**, **max memories = 2000**, **recency half-life = 14 days** — change deliberately, with tests.

## Origin

Rainman's scoring engine was extracted from [CogniTrait](https://github.com/yan-yanko/pygmalion) — a personality-shaped memory system for AI agents that uses Big Five personality traits to modulate retrieval weights. Rainman strips the personality dependencies and uses fixed weights tuned for project-knowledge retrieval.

The core algorithms (ACT-R temporal decay, keyword scoring, associative linking) are proven across CogniTrait's unit tests and validated on real-world election prediction, marketing research, and synthetic-persona workloads.

## Requirements & License

- **Python 3.10+**
- **Zero external dependencies** (standard library only)

Licensed under the **MIT License**. See [LICENSE](LICENSE).
