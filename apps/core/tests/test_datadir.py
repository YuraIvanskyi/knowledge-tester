import pytest

from apps.core.datadir import sync_warning, synced_folder_name


@pytest.mark.parametrize(
    "path, expected",
    [
        (r"C:\Users\Yurii\OneDrive\Desktop\data", "OneDrive"),
        (r"C:\Users\Yurii\OneDrive - School\kt", "OneDrive - School"),
        ("/home/u/Dropbox/kt", "Dropbox"),
        (r"G:\My Drive\kt", "My Drive"),
        (r"C:\Users\Yurii\Google Drive\kt", "Google Drive"),
        (r"C:\Users\Yurii\AppData\Local\KnowledgeTester", None),
        ("/home/u/.local/share/knowledge-tester", None),
        ("/home/u/onedrives-notes/x", None),
    ],
)
def test_synced_folder_name(path, expected):
    assert synced_folder_name(path) == expected


def test_sync_warning_text():
    assert "OneDrive" in sync_warning(r"C:\Users\x\OneDrive\kt")
    assert sync_warning(r"C:\Users\x\AppData\Local\KnowledgeTester") is None
