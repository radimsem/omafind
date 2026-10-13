"""Port of DigUp FolderSelection.swift (MIT, ARahim3/DigUp, 6faa29e)."""

import os
from pathlib import Path


class FolderSelection:
    def __init__(self, chosen=(), skipped=(), kept=()):
        self.chosen = list(dict.fromkeys(chosen))
        self.skipped = list(dict.fromkeys(skipped))
        self.kept = list(dict.fromkeys(kept))

    def is_searched(self, path):
        return self.searched(path, self.kept + self.chosen, self.skipped)

    @staticmethod
    def searched(path, folders, skipped):
        return any((path == folder or FolderSelection.is_inside(path, folder)) and not any(
            FolderSelection.is_inside(skip, folder) and (
                path == skip or FolderSelection.is_inside(path, skip)) for skip in skipped
        ) for folder in folders)

    def searched_as(self, path):
        return max((folder for folder in self.kept + self.chosen
                    if self.searched(path, [folder], self.skipped)), key=len, default=None)

    @property
    def folders(self):
        all_folders = list(dict.fromkeys(self.kept + self.chosen))
        return [folder for folder in all_folders if not any(
            other != folder and self.is_inside(folder, other)
            and self.searched(folder, [other], self.skipped) for other in all_folders)]

    @property
    def effective_skips(self):
        folders = self.folders
        return [skip for skip in self.skipped if any(self.is_inside(skip, f) for f in folders)]

    def mark(self, folder):
        if self.is_searched(folder):
            return 'mixed' if any(self.parent(s) == folder and not self.is_searched(s)
                                  for s in self.skipped) else 'on'
        return 'mixed' if any(self.parent(f) == folder for f in self.kept + self.chosen) else 'off'

    def set_folder(self, folder, on: bool):
        self.skipped = [s for s in self.skipped if self.parent(s) != folder]
        self.chosen = [f for f in self.chosen if self.parent(f) != folder]
        self.set_subfolder(folder, on)

    def set_subfolder(self, folder, on: bool):
        if on:
            self.unskip(folder)
            if not self.is_searched(folder):
                self.chosen.append(folder)
        else:
            self.chosen = [f for f in self.chosen if f != folder]
            if self.is_searched(folder) and folder not in self.skipped:
                self.skipped.append(folder)

    def unskip(self, folder):
        self.skipped = [s for s in self.skipped if s != folder]

    @staticmethod
    def is_inside(path, folder):
        return str(path).startswith(str(folder).rstrip('/') + '/')

    @staticmethod
    def parent(path):
        return os.path.dirname(path.rstrip('/')) or '/'


def to_roots(selection: FolderSelection, volume_of) -> list[dict]:
    return [{'path': folder, 'volume': volume_of(Path(folder))[0],
             'excludes': [os.path.relpath(skip, folder) for skip in selection.effective_skips
                          if selection.is_inside(skip, folder)]} for folder in selection.folders]
