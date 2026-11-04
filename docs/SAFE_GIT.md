# Owner-run Git handoff

No git add, commit or push was run by the agent. Current branch is main.
The ignored private experiment records remain on disk for local review; they are
not needed to deploy the demo. Do not force-add .env, wallet data, SQLite files,
account snapshots, build output or dependencies.

Run from the repository root, in this order. Read the staged diff before commit:

```bash
cd ~/Projects/ZPermit
backend/.venv/bin/python scripts/check_secrets.py
git diff --check
git add -- .gitignore .dockerignore Dockerfile render.yaml README.md FEEDBACK.md docs scripts frontend backend/app backend/tests backend/tools backend/docs backend/pyproject.toml backend/.env.example
git diff --cached --check
git diff --cached --stat
git diff --cached
# Proceed only after reviewing the staged content:
git commit -m "Ship isolated public demo and hackathon submission"
git push origin main
```

The scanner checks the prospective non-ignored source set against configured
local credentials without printing them, and rejects common private artifacts.
It is an additional check, not a substitute for reviewing the staged content.
Only backend/.env.example is tracked; configured values were sanitized there.
Docker copies only application source and frontend build inputs/output. No local
account snapshot, .env or database is an input to the deployed service.
