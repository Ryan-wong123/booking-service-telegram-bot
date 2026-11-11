# CLAUDE.md

Read [docs/Agents.md](docs/Agents.md) first and follow it. In particular:

- **Update [docs/PRD.md](docs/PRD.md) and [docs/Architecture.md](docs/Architecture.md) in the same commit as any change.**
- Commits must be authored by the repository owner (check `git config user.name` / `user.email`); never add AI co-author trailers or session links.
- Run `pyflakes app tests wsgi.py` and `pytest -q` before finishing, and report real results.
