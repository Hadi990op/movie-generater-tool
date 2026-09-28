#!/usr/bin/env python3
"""Unit tests for the movie generator pipeline."""
import json
import subprocess
from pathlib import Path

import pytest

from movie_generator.agnes_client import AgnesClient
from movie_generator.pipeline import MovieGenerator


@pytest.fixture
def project_dir(tmp_path):
    return str(tmp_path / "projects")


def test_extract_json_from_response():
    text = "Here is the plan:\n```json\n{\"acts\": []}\n```\n\nHope this helps!"
    result = MovieGenerator._extract_json(text)
    assert result == {"acts": []}


def test_extract_json_pure_json():
    text = '{"acts": [], "character_bank": {}}'
    result = MovieGenerator._extract_json(text)
    assert result == {"acts": [], "character_bank": {}}


def test_extract_json_failure():
    with pytest.raises(ValueError):
        MovieGenerator._extract_json("no json here at all")


def test_keystate_usage():
    from movie_generator.agnes_client import KeyState
    k = KeyState(name="test", api_key="sk-123")
    usage = k.usage
    assert usage["key"] == "test"
    assert usage["disabled"] is False
    assert usage["requests_today"] == 0


def test_client_no_keys():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b"[]")
        f.flush()
        client = AgnesClient(keys_file=f.name)
        assert len(client.keys) == 0


def test_style_bible():
    text = MovieGenerator._inject_consistency(
        "A shot of a person",
        {"location": "Office"}, {}, []
    )
    assert text == "A shot of a person"  # No matching location


def test_consistency_injection():
    text = MovieGenerator._inject_consistency(
        "A shot",
        {"location": "Office"},
        {"Office": {"canonical_desc": "A modern office with glass walls"}},
        [{"name": "Laptop", "description": "Silver MacBook", "scenes": ["s1"]}]
    )
    assert "A modern office" in text
    assert "Laptop" not in text  # Not in scenes match
