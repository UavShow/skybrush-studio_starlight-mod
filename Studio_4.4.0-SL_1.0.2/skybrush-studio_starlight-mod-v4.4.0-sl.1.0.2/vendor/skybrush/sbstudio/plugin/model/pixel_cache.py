from collections.abc import Iterator, Mapping, Sequence

__all__ = ("PixelCache",)


class PixelCache(Mapping[str, Sequence[float]]):
    

    _items: dict[str, tuple[float, ...]]
    """The cached pixels, keyed by the UUIDs of the light effects."""

    _dynamic_keys: set[str]
    """Set of keys that are not static (i.e. they are invalidated when the
    current frame changes).
    """

    def __init__(self):
        
        self._dynamic_keys = set()
        self._items = {}

    def add(self, key: str, value: Sequence[float], *, is_static: bool = False):
        
        self._items[key] = tuple(value)
        if is_static:
            self._dynamic_keys.discard(key)
        else:
            self._dynamic_keys.add(key)

    def clear(self):
        
        self._items.clear()

    def clear_dynamic(self):
        
        for key in self._dynamic_keys:
            del self._items[key]
        self._dynamic_keys.clear()

    def remove(self, key: str) -> None:
        del self._items[key]
        self._dynamic_keys.discard(key)

    def __getitem__(self, key: str) -> Sequence[float]:
        return self._items[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    
