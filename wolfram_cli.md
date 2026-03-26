# Wolfram CLI

Project-local Wolfram Alpha wrapper for agents and humans.

## Why this exists

The raw API is flexible but noisy:

- query strings need careful encoding
- response payloads are nested and irregular
- assumptions, pod states, and timeout metadata are easy to miss

This CLI hides most of that complexity and stores results in project-local state.

## Entry points

Preferred entry point from the repo root:

```bash
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli ask "population of france"
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli solve "solve x^2=4"
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli convert "10 km" --to miles
```

Fallback for local development:

```bash
.venv/bin/python .pi/skills/wolfram-cli/scripts/wolfram_cli.py ask "population of france"
```

## Commands

### `ask`

General-purpose Wolfram query.

```bash
uvx --from . wolfram-cli ask "weather shanghai"
```

### `solve`

Math-oriented query helper.

```bash
uvx --from . wolfram-cli solve "y' = y/(x+y^3)"
uvx --from . wolfram-cli solve "solve x^2=4" --steps
```

### `convert`

Unit conversion helper.

```bash
uvx --from . wolfram-cli convert "1 gallon" --to liters
```

### `inspect`

Fuller normalized payload, useful for debugging or agent follow-up logic.

```bash
uvx --from . wolfram-cli inspect "derivative of sin x" --json
```

### `history`, `last`, `sessions`, `choices`, and `apply`

The persistence layer is meant for multi-step Wolfram workflows, not just logging.

```bash
uvx --from . wolfram-cli sessions
uvx --from . wolfram-cli ask "apple" --session fruit-vs-company
uvx --from . wolfram-cli choices --session fruit-vs-company
uvx --from . wolfram-cli apply 3 --session fruit-vs-company
uvx --from . wolfram-cli history --session fruit-vs-company
uvx --from . wolfram-cli last --session fruit-vs-company
```

- `sessions` lists saved sessions and the current one
- `--session <name>` keeps related runs together
- `choices` shows numbered follow-up actions from the last saved result
- `apply <n>` reuses the saved token for an assumption or pod-state follow-up
- `history` and `last` can be scoped to one session

## Persistence

Saved state lives under:

- `.pi/wolfram/state.json`
- `.pi/wolfram/runs/*.json`

`state.json` stores recent normalized runs and session metadata.
`runs/*.json` stores the raw Wolfram `queryresult` payloads.

A session is the unit of continuous work. Each session remembers its last entry so an agent can:

- inspect the previous result
- list available follow-ups
- apply a numbered follow-up without manually passing WA tokens

## Output model

The CLI tries to return this simplified shape:

```json
{
  "success": true,
  "kind": "solve",
  "interpretation": "solve x^2=4",
  "answer": "x = ± 2",
  "alternatives": [],
  "primary_pod": {
    "id": "Result",
    "title": "Result"
  },
  "follow_up_needed": false,
  "choices": [],
  "notes": [],
  "partial": false
}
```

## Useful flags

- `--detail full` includes normalized pod summaries
- `--json` returns machine-readable output
- `--no-save` skips persistence
- `--timeout-profile fast` prefers speed over completeness
- `--session <name>` routes the run into a named continuous-work session

## Continuous flow examples

Disambiguation flow:

```bash
uvx --from . wolfram-cli ask "apple" --session demo
uvx --from . wolfram-cli choices --session demo
uvx --from . wolfram-cli apply 3 --session demo
```

Pod-state flow:

```bash
uvx --from . wolfram-cli solve "y' = y/(x+y^3)" --session ode-demo
uvx --from . wolfram-cli choices --session ode-demo
uvx --from . wolfram-cli apply 1 --session ode-demo
```

## Agent usage rule of thumb

- first query in a thread -> `ask`, `solve`, or `convert` with `--session <name>`
- follow-up on ambiguity or alternate views -> `choices` then `apply <n>`
- debugging or schema inspection -> `inspect`
