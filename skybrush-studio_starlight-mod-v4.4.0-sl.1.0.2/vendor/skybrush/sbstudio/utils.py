import importlib.util
from collections import OrderedDict
from collections.abc import Callable, Iterable, MutableMapping, Sequence
from functools import wraps
from pathlib import Path
from typing import Any, Generic, TypeVar

import numpy as np

from sbstudio.model.types import Coordinate3D

__all__ = (
    "consecutive_pairs",
    "constant",
    "create_path_and_open",
    "distance_sq_of",
    "simplify_path",
)

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


def consecutive_pairs(
    iterable: Iterable[T], cyclic: bool = False
) -> Iterable[tuple[T, T]]:
    
    it = iter(iterable)
    try:
        prev = next(it)
    except StopIteration:
        return

    first = prev if cyclic else None
    try:
        while True:
            curr = next(it)
            yield prev, curr
            prev = curr
    except StopIteration:
        pass

    if cyclic:
        assert first is not None  
        yield prev, first


def constant(value: Any) -> Callable[..., Any]:
    

    def result(*args, **kwds):
        return value

    return result


def create_path_and_open(filename, *args, **kwds):
    
    path = Path(filename)
    path.parent.mkdir(exist_ok=True, parents=True)
    return open(str(path), *args, **kwds)


def distance_sq_of(p: Coordinate3D, q: Coordinate3D) -> float:
    
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2


def get_ends(items: Iterable[T] | None) -> tuple[T, T] | None:
    
    if items is None:
        return None

    iterator = iter(items)
    try:
        first = last = next(iterator)
    except StopIteration:
        return None

    for item in iterator:
        last = item

    return (first, last)


def negate(func: Callable[..., bool]) -> Callable[..., bool]:
    

    @wraps(func)
    def new_func(*args, **kwds) -> bool:
        return not func(*args, **kwds)

    return new_func


DistanceFunc = Callable[[Iterable[T], T, T], Sequence[float]]
"""Type of a distance function used by `simplify_path`."""

EqFunc = Callable[[T, T], bool]
"""Type of an equality function used by `simplify_path`."""


def simplify_path(
    points: Sequence[T],
    *,
    eps: float,
    distance_func: DistanceFunc[T],
    eq_func: EqFunc[T],
) -> Sequence[T]:
    
    factory = points.__class__

    if len(points) < 2:
        return factory(points)  

    assert eq_func is not None

    eq_with_next = np.array(
        [eq_func(u, v) for u, v in consecutive_pairs(points)], dtype=bool
    )

    to_keep = np.full(len(points), False)
    to_keep[0] = True
    to_keep[-1] = True
    to_keep[np.diff(eq_with_next).nonzero()[0] + 1] = True

    result = []

    for start, end in consecutive_pairs(to_keep.nonzero()[0]):
        if not result:
            result.append(points[start])

        if not eq_with_next[start]:
            if eps > 0:
                _simplify_line(points, start, end, eps, distance_func, result)
            else:
                result.extend(points[(start + 1) : (end - 1)])

        result.append(points[end])

    return factory(result)  


def _simplify_line(
    points: Sequence[T],
    start: int,
    end: int,
    eps: float,
    distance_func: DistanceFunc,
    result: list[T],
) -> None:
    if end - start < 2:
        return

    dists = distance_func(points[start : (end + 1)], points[start], points[end])
    index = max(range(len(dists)), key=dists.__getitem__)
    dmax = dists[index]

    if dmax <= eps:
        return

    index += start

    result.append(points[index])
    _simplify_line(points, start, index, eps, distance_func, result)
    _simplify_line(points, index, end, eps, distance_func, result)


def load_module(path: str) -> Any:
    
    spec = importlib.util.spec_from_file_location("colors_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LRUCache(Generic[K, V], MutableMapping[K, V]):
    

    _items: OrderedDict[K, V]

    def __init__(self, capacity: int):
        
        self._items = OrderedDict()
        self._capacity = max(int(capacity), 1)

    def __delitem__(self, key: K) -> None:
        del self._items[key]

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __setitem__(self, key: K, value: V):
        self._items[key] = value
        self._items.move_to_end(key)
        if len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def get(self, key: K) -> V:
        
        value = self._items[key]
        self._items.move_to_end(key)
        return value

    def peek(self, key: K) -> V:
        
        return self._items[key]

    __getitem__ = peek
