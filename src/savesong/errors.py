"""Exception hierarchy for SaveSong."""


class SaveSongError(Exception):
    """Base class for all SaveSong errors."""


class UnsupportedURLError(SaveSongError):
    """The URL does not belong to a supported source."""


class ResolveError(SaveSongError):
    """Fetching playlist/track metadata failed."""


class SpotifyAuthError(ResolveError):
    """Spotify credentials are missing or rejected."""


class DownloadCancelled(SaveSongError):
    """Raised inside yt-dlp progress hooks to abort an in-flight download."""


class DownloadFailed(SaveSongError):
    """A track download did not produce a usable file."""


class ConversionError(SaveSongError):
    """ffmpeg conversion failed or ffmpeg is unavailable."""


class TaggingError(SaveSongError):
    """The audio container is not taggable."""
