"""URL resolvers: turn a playlist/track URL into normalized :class:`TrackMeta`."""

from savesong.core.resolvers.base import Resolver
from savesong.core.resolvers.detect import DetectedURL, detect
from savesong.core.resolvers.soundcloud import SoundCloudResolver
from savesong.core.resolvers.spotify import SpotifyResolver
from savesong.core.resolvers.ytmusic import YTMusicResolver

__all__ = [
    "DetectedURL",
    "Resolver",
    "SoundCloudResolver",
    "SpotifyResolver",
    "YTMusicResolver",
    "detect",
]
