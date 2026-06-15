"""Deterministic-run protocol — seed every source of randomness in the process.

Call ``enforce_determinism(seed)`` ONCE at the top of any run/spike script,
before constructing agents or doing any sampling. After it returns, all
seeded randomness in the process is tied to ``seed``. We need this for two
reasons specific to The Agent Exchange:

  1. The **seeded-liar protocol**: injecting known-bad worker agents
     and measuring the verifier's catch-rate is only honest if the run is
     reproducible — same seed → same liars → same claims → same catch-rate.
  2. Reproducible **/metrics** so the locked headline number can be re-derived
     from logs, not re-rolled.

PYTHONHASHSEED can only take effect if set BEFORE the interpreter starts;
setting it mid-process does not change the current interpreter's hashing.
We set it anyway (so child processes inherit it) and WARN if the inherited
value disagrees — relaunch under ``PYTHONHASHSEED=<seed> python ...`` for a
fully deterministic run. numpy/torch are optional (Mac-dev hosts skip them).
"""

from __future__ import annotations

import os
import random
import warnings
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeterminismReport:
    """What ``enforce_determinism`` did this call (for tests / verification)."""

    seed: int
    pythonhashseed_ok: bool  # did the inherited PYTHONHASHSEED match? (False ⇒ set hashing non-deterministic)
    numpy_seeded: bool       # was numpy importable + seeded?


def enforce_determinism(seed: int) -> DeterminismReport:
    """Seed every controllable source of randomness in this process.

    Idempotent for a fixed seed. Raises ``ValueError`` on a negative/non-int seed.
    """
    if not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed must be a non-negative int, got {seed!r}")

    # 1. stdlib random
    random.seed(seed)

    # 2. PYTHONHASHSEED — propagate to children; warn if the current process didn't inherit it.
    inherited = os.environ.get("PYTHONHASHSEED")
    pythonhashseed_ok = inherited == str(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    if not pythonhashseed_ok:
        warnings.warn(
            f"PYTHONHASHSEED was {inherited!r} at process start; requested seed is {seed}. "
            f"Hash-based iteration (sets/frozensets/dict-by-hash) is NOT reproducible in THIS "
            f"process. For a fully deterministic run, relaunch under "
            f"`PYTHONHASHSEED={seed} python ...`.",
            RuntimeWarning,
            stacklevel=2,
        )

    # 3. numpy legacy global RNG — optional.
    numpy_seeded = False
    try:
        import numpy as np  # noqa: PLC0415 (optional dependency)

        np.random.seed(seed)
        numpy_seeded = True
    except ImportError:
        pass

    return DeterminismReport(
        seed=seed,
        pythonhashseed_ok=pythonhashseed_ok,
        numpy_seeded=numpy_seeded,
    )
