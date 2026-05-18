

from collections.abc import Callable, Sequence
from random import Random
from threading import Lock
from typing import Self


class RandomSequence(Sequence[int]):
    

    _cache: list[int]
    """Cached items of the sequence that were already generated."""

    _max: int
    """Maximum value that can be returned in the sequence."""

    _rng: Random
    """Internal RNG that generates the sequence."""

    _rng_factory: Callable[[int | None], Random]
    """Factory function that created the internal RNG of this sequence, used
    for forking.
    """

    _lock: Lock
    """Lock that guarantees that only one thread is allowed to extend the
    cached items of the sequence.
    """

    def __init__(
        self,
        *,
        seed: int | None = None,
        max: int = 0xFFFFFFFF,
        rng_factory: Callable[[int | None], Random] = Random,
    ):
        
        self._cache = []
        self._rng_factory = rng_factory
        self._rng = rng_factory(seed)
        self._max = max
        self._lock = Lock()

    def __getitem__(self, index: int) -> int:
        if len(self._cache) <= index:
            self._ensure_length_is_at_least(index + 1)
        return self._cache[index]

    def __len__(self) -> int:
        return len(self._cache)

    def _ensure_length_is_at_least(self, length: int) -> None:
        with self._lock:
            while len(self._cache) < length:
                self._cache.append(self._rng.randint(0, self._max))

    def fork(self, index: int) -> Self:
        
        return self.__class__(
            seed=self[index], max=self._max, rng_factory=self._rng_factory
        )

    def get(self, index: int) -> int:
        
        return self[index]

    def get_float(self, index: int) -> float:
        
        return self[index] / self.max

    @property
    def max(self) -> int:
        
        return self._max
