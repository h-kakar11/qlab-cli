"""Entry point.

    py analyse.py                # interactive prompt
    py analyse.py NVDA           # report, then the prompt
    py analyse.py NVDA --once    # report and exit
    py analyse.py NVDA --live    # live streaming table

Do not rename this file to `massive.py` — a module of that name in the project
root shadows the installed `massive` package and silently kills that provider.
"""

from __future__ import annotations

from qa.cli import run

if __name__ == "__main__":
    raise SystemExit(run())
