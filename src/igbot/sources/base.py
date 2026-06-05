"""Source interface. Each source yields :class:`Candidate` objects."""

from __future__ import annotations

from typing import Iterator, Protocol

from ..config import Feed
from ..models import Candidate


class Source(Protocol):
    name: str

    def fetch(self, feed: Feed) -> Iterator[Candidate]:
        """Yield candidates for a feed (already filtered by score/window/type)."""
        ...
