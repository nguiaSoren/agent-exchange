"""Logging helpers — the `/tmp` full-capture convention.

Background/unattended runs (spikes, agent fleets, paid cycles) must write their
FULL output to a `/tmp` file, never `| tail` — you always end up needing the
errors you'd have truncated. ``run_logfile("xspike")`` returns a fresh, unique
``/tmp/agentexch_xspike_<unix>.log`` path; ``configure_file_logging`` wires the
stdlib logger to tee into it.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path


def run_logfile(task: str) -> Path:
    """A unique full-capture log path for a background run, e.g.
    ``/tmp/agentexch_xspike_1718200000.log``. Caller redirects into it:
    ``... > "$(path)" 2>&1`` — full capture, no ``| tail``."""
    return Path("/tmp") / f"agentexch_{task}_{int(time.time())}.log"


def configure_file_logging(task: str, level: int = logging.INFO) -> Path:
    """Send root-logger output to both stderr and a fresh `/tmp` file. Returns the path."""
    path = run_logfile(task)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    logging.getLogger(__name__).info("logging to %s", path)
    return path
