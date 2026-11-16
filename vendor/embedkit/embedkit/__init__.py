"""embedkit — embedded AI toolkit: hardware probe, model registry, licence policy, in-process runtimes.

embedkit knows nothing about the applications that use it.
"""

__version__ = "0.1.0"


class EmbedkitError(Exception):
    """Base error; messages are written for the end user, in French."""
