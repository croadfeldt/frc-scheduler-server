"""Base class for scheduling adapters.

An adapter wraps one scheduling tool (the reference scheduler, our scheduler, CP-SAT,
or "the published schedule") behind a uniform interface so the harness
can compare them apples-to-apples.

Adapters are stateless except for configuration. A single adapter
instance can generate(fixture) for many fixtures sequentially or
concurrently. Concurrent calls must not share state — this is enforced
by convention rather than locking; if you need state, instantiate a
fresh adapter per worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..harness_types import Fixture, Schedule


class Adapter(ABC):
    """Generate a Schedule for a given Fixture."""

    name: str = "abstract"

    @abstractmethod
    def generate(self, fixture: Fixture, *, seed: int | None = None,
                 trial: int = 0) -> Schedule:
        """Produce one schedule.

        Stochastic adapters honor `seed` for reproducibility. Deterministic
        adapters ignore it. `trial` is the harness's iteration index when
        running best-of-N — adapters can use it for filename uniqueness
        or as a derived seed.

        Implementations should populate Schedule.generation_seconds
        and Schedule.adapter_diagnostics with anything useful for
        post-hoc analysis (internal score, iteration count, time
        budget used vs available, etc.).
        """
        ...
