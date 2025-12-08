from dataclasses import dataclass, field
from typing import List


@dataclass
class InMemoryFile:
    name: str
    mime: str
    data: bytes


@dataclass
class SessionAccumulator:
    files: List[InMemoryFile] = field(default_factory=list)

    def add_file(self, f: InMemoryFile):
        self.files.append(f)

    def count(self) -> int:
        return len(self.files)

    def clear(self):
        # Явная очистка буферов
        self.files.clear()