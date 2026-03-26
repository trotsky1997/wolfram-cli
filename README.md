# wolfram-cli

Agent-friendly Wolfram Alpha CLI with project-local sessions, follow-up actions, and a pi skill.

## Install / run

From the repo root:

```bash
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli ask "population of france"
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli solve "solve x^2=4"
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli convert "10 km" --to miles
```

## Continuous workflow

The CLI is built around saved sessions so follow-up queries do not need raw Wolfram tokens.

```bash
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli ask "apple" --session demo
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli choices --session demo
uvx --from git+https://github.com/trotsky1997/wolfram-cli wolfram-cli apply 3 --session demo
```

## Main commands

- `ask` - general Wolfram query
- `solve` - math-oriented query helper
- `convert` - unit conversion helper
- `inspect` - fuller normalized response for debugging
- `sessions` - list saved sessions
- `history` / `last` - inspect saved runs
- `choices` / `apply` - continue a saved Wolfram workflow

## Project structure

- `src/wolfram_cli_tool/cli.py` - packaged CLI entrypoint
- `.pi/skills/wolfram-cli/SKILL.md` - pi project skill
- `wolfram_cli.md` - fuller usage guide

## Notes

- Runtime state is stored in `.pi/wolfram/` and is intentionally gitignored.
- The CLI returns simplified, agent-friendly output instead of raw Wolfram payloads by default.
