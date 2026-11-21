import contextvars
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy

import tradingagents.default_config as default_config

# Use default config but allow it to be overridden
_config: dict | None = None

#: A config snapshot local to one execution context, or ``None``.
#:
#: ``config_snapshot`` sets this for the block it wraps. Calls made inside that
#: block -- in the same thread or asyncio task -- read the snapshot instead of
#: the global config, so a value one caller snapshotted cannot be changed by
#: another caller's ``set_config`` while its request is in flight. The global
#: config is never written: an update made elsewhere is still there afterwards,
#: and only this context sees the snapshot.
_SNAPSHOT: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "tradingagents_config_snapshot", default=None
)


@contextmanager
def config_snapshot(config: Mapping):
    """Read ``config`` instead of the global config for the block.

    ``config`` is copied on entry, so later changes to the caller's dict are not
    seen. The previous snapshot (or the absence of one) is restored from the
    token in a ``finally``, so a normal return, an exception, a cancellation and
    an interruption all release it. Nothing global is touched.
    """
    pinned = deepcopy(dict(config))
    token = _SNAPSHOT.set(pinned)
    try:
        yield pinned
    finally:
        _SNAPSHOT.reset(token)


def snapshot_active() -> bool:
    """Whether the current execution context is reading a snapshot."""
    return _SNAPSHOT.get() is not None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: dict):
    """Update the configuration with custom values.

    Dict-valued keys (e.g. ``data_vendors``) are merged one level deep so a
    partial update like ``{"data_vendors": {"core_stock_apis": "alpha_vantage"}}``
    keeps the other nested keys from the default; scalar keys are replaced.
    """
    global _config
    initialize_config()
    incoming = deepcopy(config)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(_config.get(key), dict):
            _config[key].update(value)
        else:
            _config[key] = value


def get_config() -> dict:
    """Get the current configuration.

    Inside a :func:`config_snapshot` block this returns that snapshot instead
    of the global config, so everything the context calls -- including a vendor
    that reads a request parameter at call time -- sees one consistent config.
    """
    snapshot = _SNAPSHOT.get()
    if snapshot is not None:
        return deepcopy(snapshot)
    if _config is None:
        initialize_config()
    return deepcopy(_config)


# Initialize with default config
initialize_config()
