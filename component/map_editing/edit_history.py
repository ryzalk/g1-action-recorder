"""Undo and redo.

The only place that writes an edit into a MapDocument, so apply and revert
stay mirror images of each other.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dataclasses import dataclass

import numpy as np
from loguru import logger

from component.map_storage.service import MapDocument, MapStorage
from config.settings import use_utf8_output


@dataclass
class EditCommand:
    id: int
    tool: str
    action: str                          # "erase" | "obstacle"
    geometry: dict
    params: dict
    bbox: tuple[int, int, int, int]
    grid_before: np.ndarray
    grid_after: np.ndarray
    map_idx: np.ndarray
    ground_idx: np.ndarray
    summary: str                         # "Lasso erase · grid + points · 120 cells · 1,284 points deleted"


class EditHistory:
    def __init__(self) -> None:
        self.done = []
        self.undone = []
        self.next_id = 1

    def new_id(self) -> int:
        command_id = self.next_id
        self.next_id += 1
        return command_id

    def execute(self, document: MapDocument, command: EditCommand) -> None:
        """Apply and record. A new command drops the redo stack."""
        self._apply(document, command)
        self.done.append(command)
        self.undone.clear()

    def undo(self, document: MapDocument) -> EditCommand | None:
        """An empty stack is a no-op and returns None."""
        if not self.done:
            return None
        command = self.done.pop()
        self._revert(document, command)
        self.undone.append(command)
        return command

    def redo(self, document: MapDocument) -> EditCommand | None:
        if not self.undone:
            return None
        command = self.undone.pop()
        self._apply(document, command)
        self.done.append(command)
        return command

    def jump(self, document: MapDocument, command_id: int) -> list[EditCommand]:
        """Undo or redo until command_id is the latest applied one; 0 means before the first.
        Returns the commands that were undone or redone, in order."""
        moved = []
        while self.done and self.done[-1].id > command_id:
            moved.append(self.undo(document))
        while self.undone and self.undone[-1].id <= command_id:
            moved.append(self.redo(document))
        return moved

    def entries(self) -> list[dict]:
        """Oldest first; undone commands follow the done ones in the order they were made."""
        entries = [{"id": command.id, "summary": command.summary, "undone": False} for command in self.done]
        entries += [{"id": command.id, "summary": command.summary, "undone": True} for command in reversed(self.undone)]
        return entries

    def done_ids(self) -> tuple[int, ...]:
        ids = tuple(command.id for command in self.done)
        return ids

    def clear(self) -> None:
        """A new history (another map, or the original restored): numbering starts again at #1."""
        self.done.clear()
        self.undone.clear()
        self.next_id = 1

    @staticmethod
    def _apply(document: MapDocument, command: EditCommand) -> None:
        r0, r1, c0, c1 = command.bbox
        document.grid.image[r0:r1, c0:c1] = command.grid_after
        document.map_deleted[command.map_idx] = True
        document.ground_deleted[command.ground_idx] = True

    @staticmethod
    def _revert(document: MapDocument, command: EditCommand) -> None:
        r0, r1, c0, c1 = command.bbox
        document.grid.image[r0:r1, c0:c1] = command.grid_before
        # Safe because map_idx only ever holds points this command itself marked.
        document.map_deleted[command.map_idx] = False
        document.ground_deleted[command.ground_idx] = False


def demo_history() -> None:
    """Three overlapping synthetic commands: undo all -> exactly the start; redo all -> exactly the end."""
    document = MapStorage().load()
    history = EditHistory()
    generator = np.random.default_rng(1)
    start = (document.grid.image.copy(), document.map_deleted.copy(), document.ground_deleted.copy())

    for index in range(3):
        r0, c0 = 100 + index * 10, 120 + index * 10
        bbox = (r0, r0 + 40, c0, c0 + 40)
        before = document.grid.image[r0:r0 + 40, c0:c0 + 40].copy()
        after = np.full_like(before, (0, 205, 254)[index])
        candidates = np.flatnonzero(~document.map_deleted)
        command = EditCommand(
            id=history.new_id(), tool="lasso_erase", action="erase", geometry={}, params={}, bbox=bbox,
            grid_before=before, grid_after=after,
            map_idx=generator.choice(candidates, 500, replace=False), ground_idx=np.arange(index * 10, index * 10 + 10),
            summary=f"Made-up command {index + 1}")
        history.execute(document, command)
    end = (document.grid.image.copy(), document.map_deleted.copy(), document.ground_deleted.copy())

    while history.undo(document) is not None:
        pass
    assert all(np.array_equal(now, then) for now, then in
               zip((document.grid.image, document.map_deleted, document.ground_deleted), start, strict=False))
    while history.redo(document) is not None:
        pass
    assert all(np.array_equal(now, then) for now, then in
               zip((document.grid.image, document.map_deleted, document.ground_deleted), end, strict=False))
    history.undo(document)
    history.execute(document, EditCommand(
        id=history.new_id(), tool="polygon_fill", action="obstacle", geometry={}, params={}, bbox=(0, 1, 0, 1),
        grid_before=document.grid.image[0:1, 0:1].copy(), grid_after=np.zeros((1, 1), np.uint8),
        map_idx=np.zeros(0, np.int64), ground_idx=np.zeros(0, np.int64), summary="New command"))
    assert not history.undone, "a new command should clear the redo stack"
    logger.info("Undo all matches the start, redo all matches the end, a new command clears redo. History: {}",
                [(entry["id"], entry["undone"]) for entry in history.entries()])

    moved = history.jump(document, 0)
    assert np.array_equal(document.grid.image, start[0]) and not history.done
    history.jump(document, 2)
    assert history.done_ids() == (1, 2) and [command.id for command in history.undone] == [4]
    logger.info("Jump to the start undid {}; jump to #2: done {}, redoable {}", len(moved), history.done_ids(),
                [command.id for command in history.undone])

    history.clear()
    assert not history.done and not history.undone and history.new_id() == 1, "clearing restarts numbering at #1"
    logger.info("After clearing the history the next command is #1")


def main() -> None:
    use_utf8_output()
    demo_history()


if __name__ == "__main__":
    main()
