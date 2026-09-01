---
description: Run the krkn chaos coverage scan with an interactive configuration wizard.
agent: build
---

Run the project scan using the shared, harness-neutral CLI.

If the user's request includes explicit values, preserve them and pass them as
flags. If values are missing, use the `question` tool to ask for release,
agent scope, lookback days, scan mode, and filter stages, then pass the answers
as explicit CLI flags. Do not launch an interactive stdin wizard from an agent
shell, because many harnesses do not provide a TTY.

For a human terminal, the same questions are available with:

```bash
PYTHONPATH=. venv/bin/python src/main.py --interactive
```

The wizard prompts for release, agent scope, lookback days, scan mode, and
filter stages. Never select or create GitHub issues without asking the user
first; answer `none` at the final issue prompt unless the user has explicitly
approved specific issues.

For non-interactive automation, skip the wizard and pass flags directly, for
example:

```bash
PYTHONPATH=. venv/bin/python src/main.py --release 4.21 --agent control_plane --days 14 --max-bugs 50
```
