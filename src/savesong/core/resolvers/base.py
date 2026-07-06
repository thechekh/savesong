"""Resolver interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from savesong.models import Resolved, Source


class Resolver(ABC):
    """Turns a supported URL into normalized playlist/track metadata."""

    source: ClassVar[Source]

    @abstractmethod
    async def resolve(self, url: str) -> Resolved:
        """Fetch metadata for ``url``; raises :class:`savesong.errors.ResolveError`."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook, deliberately non-abstract
        """Release any owned network resources (default: nothing to do)."""
