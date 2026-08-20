# Contributing

This is a safety-critical wrapper around nwipe. Prefer obvious code over clever code.

## Rules

- Conventional commits: `feat:`, `fix:`, `docs:`, `safety:`.
- Any change to disk selection or nwipe flags is `safety:` and needs a test.
- Never commit ISOs, USB images, or secrets.
- `main` should stay releasable.
- Do not add a new wipe engine, password tools, or Secure Boot circumvention.

## Checks

```bash
python3 -m pytest
```

Open PRs into `main`.
