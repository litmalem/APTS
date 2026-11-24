"""Read-only fingerprints of configured local DB locations for deployment diagnostics.

These identify configuration, not data integrity or authorization. No DB is
opened or created; realpath resolves aliases to the same local source location.
"""
import hashlib
import os


def source_location(kind, path):
    normalized = os.path.normcase(os.path.realpath(os.fspath(path)))
    return hashlib.sha256(("APTS_LOCAL_SOURCE_LOCATION_V1\0"+kind+"\0"+normalized).encode("utf-8")).hexdigest()
