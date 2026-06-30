"""Tests para data/avatars.py — validación y guardado de stickers .webp."""

from __future__ import annotations

import os

import pytest

import data.avatars as avatars
from data.avatars import is_webp, save_avatar


def _webp_bytes() -> bytes:
    # Cabecera RIFF....WEBP + relleno.
    return b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8 fake payload"


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"fake png data"


class TestIsWebp:
    def test_valid_webp(self):
        assert is_webp(_webp_bytes()) is True

    def test_png_rejected(self):
        assert is_webp(_png_bytes()) is False

    def test_too_short(self):
        assert is_webp(b"RIFF") is False


class TestSaveAvatar:
    def test_rejects_non_webp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(avatars, "AVATARS_DIR", str(tmp_path))
        with pytest.raises(ValueError):
            save_avatar(7, _png_bytes())
        assert not os.path.exists(tmp_path / "7.webp")

    def test_saves_and_returns_url(self, tmp_path, monkeypatch):
        monkeypatch.setattr(avatars, "AVATARS_DIR", str(tmp_path))
        url = save_avatar(7, _webp_bytes())
        assert (tmp_path / "7.webp").exists()
        assert url.startswith("/avatars/7.webp?v=")

    def test_overwrites_same_player(self, tmp_path, monkeypatch):
        monkeypatch.setattr(avatars, "AVATARS_DIR", str(tmp_path))
        save_avatar(7, _webp_bytes())
        save_avatar(7, _webp_bytes() + b"more")
        # Sigue habiendo un solo archivo para el jugador 7.
        files = [f for f in os.listdir(tmp_path) if f.startswith("7")]
        assert files == ["7.webp"]
