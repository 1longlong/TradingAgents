"""Single-file atomic replacement, shared by the report writer and the state log.

``write_text_atomic`` never writes into the target in place: it writes the whole
payload to a uniquely named temporary file in the target's own directory,
flushes it to disk and closes it, then ``os.replace``-es it over the target.
A reader therefore sees either the previous file or the new one, never a
truncated mix, and a failure leaves the previous file untouched.

The temporary file must live in the same directory so the replace stays on one
filesystem (``os.replace`` is only atomic within a filesystem). On Windows the
temporary file has to be closed before it can be replaced, so the handle is
always closed before the swap.

Scope: this is a per-file guarantee, not a transaction across several files.
Writing a report directory or updating the state log replaces each file on its
own; if a later file fails, earlier files keep their new contents and no
attempt is made to roll them back.
"""

import contextlib
import os
import tempfile
from pathlib import Path

_TEMP_PREFIX = "."
_TEMP_SUFFIX = ".tmp"


def write_text_atomic(target, text: str, encoding: str = "utf-8") -> None:
    """Replace ``target`` with ``text`` as one atomic step per file.

    The caller is expected to have serialised ``text`` completely already, so a
    serialisation error never reaches the filesystem.

    On any failure (creating/writing/flushing the temporary file, or the
    replace) the exception propagates unchanged: the previous ``target`` stays
    as it was, a target that did not exist stays absent, and only the temporary
    file created by this call is removed. No retry is attempted.
    """
    target = Path(target)
    directory = target.parent
    fd, temp_name = tempfile.mkstemp(
        dir=directory,
        prefix=f"{_TEMP_PREFIX}{target.name}.",
        suffix=_TEMP_SUFFIX,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # Closed here: Windows refuses to replace an open file.
        os.replace(temp_path, target)
    except BaseException:
        # Only this call's temporary file is removed. A failure to remove it
        # must not hide the error that caused the cleanup.
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise
