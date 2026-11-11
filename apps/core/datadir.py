"""Data folder checks (plan §19.3). Pure helpers, no Django imports."""

from pathlib import Path

# Folder names used by cloud sync clients. Matched case-insensitively against path parts.
_SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "my drive")


def synced_folder_name(path: str | Path) -> str | None:
    """Return the sync client a path appears to live in (e.g. "OneDrive"), or None."""
    for part in Path(path).parts:
        lowered = part.lower()
        for marker in _SYNC_MARKERS:
            if (
                lowered == marker
                or lowered.startswith(marker + " -")
                or lowered.startswith(marker + "-")
            ):
                return part
    return None


def sync_warning(path: str | Path) -> str | None:
    """A human-readable warning if the data folder is inside a sync client folder."""
    name = synced_folder_name(path)
    if name is None:
        return None
    return (
        f"The data folder {path} is inside '{name}'. Sync clients can corrupt the SQLite "
        "database. Move it outside (set KT_DATA_DIR, default %LOCALAPPDATA%\\KnowledgeTester)."
    )
