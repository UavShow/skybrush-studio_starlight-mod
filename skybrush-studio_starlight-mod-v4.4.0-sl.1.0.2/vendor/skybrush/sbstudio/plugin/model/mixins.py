from __future__ import annotations

from typing import TYPE_CHECKING, Generic, Sequence, TypeVar, cast

if TYPE_CHECKING:
    from bpy.types import bpy_prop_collection_idprop  

T = TypeVar("T")


class ListMixin(Generic[T]):
    

    entries: Sequence[T]  
    active_entry: T
    active_entry_index: int

    def move_active_entry_down(self) -> None:
        
        index = self.active_entry_index
        num_entries = len(self.entries)
        if index < num_entries - 1:
            this_entry = self.entries[index]
            next_entry = self.entries[index + 1]

            if self._on_active_entry_moving_down(this_entry, next_entry):
                cast("bpy_prop_collection_idprop[T]", self.entries).move(
                    index, index + 1
                )
                self.active_entry_index = index + 1

    def move_active_entry_up(self) -> None:
        
        index = self.active_entry_index
        if index > 0:
            prev_entry = self.entries[index - 1]
            this_entry = self.entries[index]

            if self._on_active_entry_moving_up(this_entry, prev_entry):
                cast("bpy_prop_collection_idprop[T]", self.entries).move(
                    index, index - 1
                )
                self.active_entry_index = index - 1

    def _on_active_entry_moving_down(self, this_entry, next_entry) -> bool:
        return True

    def _on_active_entry_moving_up(self, this_entry, prev_entry) -> bool:
        return True

    def _on_removing_entry(self, entry) -> bool:
        return True

    def remove_active_entry(self) -> None:
        
        entry = self.active_entry
        if not entry:
            return

        if self._on_removing_entry(entry):
            index = self.active_entry_index
            self.entries.remove(index)
            self.active_entry_index = min(max(0, index), len(self.entries))
