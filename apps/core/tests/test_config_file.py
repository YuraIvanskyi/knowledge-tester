"""kt.toml: the generated secret key is appended without damaging a hand-edited file."""

import tomllib

from config.settings.base import _load_config


def test_a_missing_file_gets_a_key(tmp_path):
    config = _load_config(tmp_path)
    assert config["secret_key"]
    assert tomllib.loads((tmp_path / "kt.toml").read_text(encoding="utf-8")) == config


def test_a_file_without_a_trailing_newline_stays_valid(tmp_path):
    (tmp_path / "kt.toml").write_text("port = 8000", encoding="utf-8")  # no newline at the end
    config = _load_config(tmp_path)
    on_disk = tomllib.loads((tmp_path / "kt.toml").read_text(encoding="utf-8"))
    assert on_disk["port"] == 8000 and on_disk["secret_key"] == config["secret_key"]


def test_an_existing_key_is_kept_and_nothing_is_written(tmp_path):
    (tmp_path / "kt.toml").write_text('secret_key = "keep-me"\n', encoding="utf-8")
    assert _load_config(tmp_path)["secret_key"] == "keep-me"
    assert (tmp_path / "kt.toml").read_text(encoding="utf-8") == 'secret_key = "keep-me"\n'


def test_the_environment_key_leaves_the_file_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("KT_SECRET_KEY", "from-the-environment")
    _load_config(tmp_path)
    assert not (tmp_path / "kt.toml").exists()
