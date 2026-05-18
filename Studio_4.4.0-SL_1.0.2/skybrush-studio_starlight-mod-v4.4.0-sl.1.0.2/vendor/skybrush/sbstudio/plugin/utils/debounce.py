from functools import wraps
from time import monotonic

import bpy

__all__ = ("debounced",)


def debounced(delay):
    

    def decorator(func):
        

        _timer_registered = False
        _last_interaction_at = None
        _last_args = None
        _last_kwds = None

        def has_interaction_ended_timer():
            nonlocal _last_interaction_at, _last_args, _last_kwds, _timer_registered

            if monotonic() - _last_interaction_at > delay:
                
                func(*_last_args, **_last_kwds)

                _timer_registered = False
                _last_interaction_at = None
                _last_args = None
                _last_kwds = None

                return None
            else:
                
                return delay / 2

        @wraps(func)
        def debounced(*args, **kwds):
            
            nonlocal _last_interaction_at, _last_args, _last_kwds, _timer_registered

            _last_interaction_at = monotonic()
            _last_args = args
            _last_kwds = kwds

            if not _timer_registered:
                _timer_registered = True
                bpy.app.timers.register(has_interaction_ended_timer)

        debounced.now = func

        return debounced

    return decorator
