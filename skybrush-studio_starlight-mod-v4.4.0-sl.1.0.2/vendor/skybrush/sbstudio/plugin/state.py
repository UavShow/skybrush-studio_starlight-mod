

import json
from abc import ABCMeta, abstractmethod
from typing import Any

import bpy
from bpy.app.handlers import persistent

from .utils import (
    create_internal_id,
    ensure_object_exists_in_collection,
    get_object_in_collection,
)


class StateBase(metaclass=ABCMeta):
    

    @abstractmethod
    def from_json(self, data: dict[str, Any]) -> None:
        
        raise NotImplementedError

    def reset(self) -> None:
        
        pass

    @abstractmethod
    def to_json(self) -> dict[str, Any]:
        
        raise NotImplementedError


class _SkybrushStudioFileState:
    

    _initialized: bool = False

    def from_json(self, data: dict[str, Any]) -> None:
        self._initialized = bool(data.get("initialized", False))

    def reset(self) -> None:
        self._initialized = False

    def to_json(self) -> dict[str, Any]:
        
        return {"initialized": self._initialized}

    def ensure_initialized(self) -> None:
        
        if not self._initialized:
            self._initialize()
            self._initialized = True

    def _initialize(self) -> None:
        
        pass


_file_specific_state = _SkybrushStudioFileState()
"""File-specific state object."""


def get_file_specific_state() -> _SkybrushStudioFileState:
    
    return _file_specific_state


def _load(key: str, state: StateBase) -> None:
    
    key = "." + create_internal_id(key)
    try:
        block = get_object_in_collection(bpy.data.texts, key)
    except KeyError:
        block = None
    if block:
        data = json.loads(block.as_string())
        state.from_json(data)


def _save(key: str, state: StateBase) -> None:
    
    data = json.dumps(state.to_json())

    key = "." + create_internal_id(key)
    block, _ = ensure_object_exists_in_collection(bpy.data.texts, key)
    block.from_string(data)


@persistent
def _load_file_specific_state(_dummy):
    _file_specific_state.reset()
    _load("State", _file_specific_state)


@persistent
def _save_file_specific_state(_dummy):
    _save("State", _file_specific_state)


def register() -> None:
    
    if _load_file_specific_state not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_file_specific_state)
    if _save_file_specific_state not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_save_file_specific_state)


def unregister() -> None:
    
    if _save_file_specific_state in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_save_file_specific_state)
    if _load_file_specific_state in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_file_specific_state)
