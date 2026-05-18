from contextlib import contextmanager
from functools import wraps
from typing import Callable, ParamSpec

__all__ = ("Suspension",)

P = ParamSpec("P")


class Suspension:
    

    _counter: int

    def __init__(self):
        self._counter = 0

    @contextmanager
    def use(self):
        
        self._counter += 1
        try:
            yield
        finally:
            self._counter -= 1

    def wrap(self, func: Callable[P, None]) -> Callable[P, None]:
        

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
            if self._counter <= 0:
                return func(*args, **kwargs)

        return wrapper
