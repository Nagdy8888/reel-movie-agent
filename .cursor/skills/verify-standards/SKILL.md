---
name: verify-standards
description: Run the project's definition-of-done gate before finishing a change - ruff (incl. docstring D rules) + format, pyright, pytest, plus structure and docstring checks. Use after implementing or modifying code in apps/agents or apps/backend, or when asked to verify/lint/check the code.
disable-model-invocation: true
---

# Verify Standards

The "definition of done" gate. Run this after any code change in `apps/agents` or `apps/backend`; do not consider work complete until it passes.

## Checks

```
- [ ] ruff (incl. D docstring rules)
- [ ] ruff format
- [ ] pyright
- [ ] pytest
- [ ] structure + docstring gate
```

Run from the repo root:

```bash
uv run ruff check .            # incl. pydocstyle D rules; fails on missing docstrings
uv run ruff format --check .   # formatting
uv run pyright                 # type check
uv run pytest                  # tests
```

Frontend changes additionally: `pnpm --dir apps/frontend lint` and `pnpm --dir apps/frontend tsc --noEmit`.

## Manual gate

- **Structure:** new files sit in the correct `apps/*` location (see the `project-structure` rule). No cross-app imports; no god files.
- **Docstrings:** every module/class/function/method has one; LangGraph nodes use the contract docstring. If `ruff` `D` is somehow not catching a case, fix it anyway.
- **Field descriptions:** new Pydantic/settings fields have `Field(description=...)`.

## Output

Report a short pass/fail checklist. If anything fails, fix it and re-run — do not stop at a red gate.
