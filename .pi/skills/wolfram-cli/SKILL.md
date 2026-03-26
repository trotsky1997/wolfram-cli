---
name: wolfram-cli
description: Use the project Wolfram CLI for Wolfram Alpha style lookups, symbolic math, equation solving, ODEs, integrals, derivatives, unit conversions, and result inspection. Make sure to use this skill whenever the user asks for Wolfram Alpha behavior, math-heavy reasoning, conversions, or factual lookups that fit WA better than ad hoc web or manual HTTP requests. Prefer the CLI commands over hand-built API calls because they handle encoding, result extraction, and project-local persistence.
---

# Wolfram CLI

Use the project CLI instead of hand-crafting HTTP calls.

## When to use

Use this skill when the user wants any of the following:

- general Wolfram-style query answering
- symbolic math or equation solving
- integrals, derivatives, limits, sums, ODEs
- unit conversions
- inspecting a previous Wolfram run saved in this project

## Main commands

Run the CLI from Git with `uvx`:

```bash
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli ask <query>
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli solve <problem>
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli convert <value> --to <unit>
```

Examples:

```bash
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli ask "population of france"
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli solve "y' = y/(x+y^3)"
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli solve "solve x^2=4" --steps
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli convert "10 km" --to miles
```

## Agent workflow

Default behavior:

1. Pick the simplest matching command: `ask`, `solve`, or `convert`.
2. If the work may continue, start with `--session <short-name>` so the next turn can reuse it.
3. Read the CLI output first; it already extracts the answer, interpretation, notes, and follow-up actions.
4. If the user wants a different interpretation or alternate view, use `choices` then `apply <n>` instead of hand-building WA tokens.
5. If the user asks for deeper inspection, rerun with `inspect` or `--detail full`.
6. Reuse saved results with `history`, `last`, or `sessions` instead of re-querying when appropriate.

## Persistence

The CLI writes project-local state to:

- `.pi/wolfram/state.json`
- `.pi/wolfram/runs/*.json`

Use these commands to inspect saved runs and continue them:

```bash
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli sessions
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli history
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli last
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli choices --session demo
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli apply 1 --session demo
```

## Useful options

- `--session <name>` to keep a multi-step Wolfram thread together
- `--detail full` to include normalized pod summaries
- `--json` for machine-readable output
- `--no-save` to skip persistence
- `--timeout-profile fast` for quicker but less complete responses
- `inspect <query>` for a fuller normalized response with pod summaries and raw key list

## Notes

- The CLI uses the project's persistent store automatically.
- Sessions are the intended unit of continuous work.
- It prefers textual results and hides raw Wolfram response complexity unless you ask for inspection.
- If the result is ambiguous or exposes alternate pod states, use `choices` and `apply` instead of guessing or manually copying tokens.
