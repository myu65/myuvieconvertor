class VideoAIError(RuntimeError):
    """Base error shown to CLI users without an internal traceback."""


class ConfigurationError(VideoAIError):
    """The requested pipeline configuration is invalid."""


class BackendError(VideoAIError):
    """An upstream model backend failed or did not create its artifact."""


class UnsafePathError(VideoAIError):
    """A job request attempted to escape its allowed stage directory."""
