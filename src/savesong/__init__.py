"""SaveSong — multi-source playlist downloader with a typed async core."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("savesong")
except PackageNotFoundError:  # pragma: no cover - running from a raw checkout
    __version__ = "0.0.0"

__all__ = ["__version__"]
