# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Ingestion must refuse a source with no content, whatever fetched it."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openviking.parse.accessors.base import LocalResource, SourceType
from openviking.server.models import ERROR_CODE_TO_HTTP_STATUS
from openviking.utils.media_processor import UnifiedResourceProcessor
from openviking_cli.exceptions import InvalidArgumentError


def _resource(path: Path, **meta) -> LocalResource:
    return LocalResource(
        path=path,
        source_type=meta.pop("source_type", SourceType.LOCAL),
        original_source=str(path),
        meta=meta or {"original_filename": path.name},
        is_temporary=False,
    )


def _processor(monkeypatch, resource: LocalResource) -> UnifiedResourceProcessor:
    """A UnifiedResourceProcessor whose accessor returns exactly ``resource``."""
    processor = UnifiedResourceProcessor.__new__(UnifiedResourceProcessor)
    monkeypatch.setattr(
        processor,
        "_get_accessor_registry",
        lambda: SimpleNamespace(access=AsyncMock(return_value=resource)),
        raising=False,
    )
    return processor


@pytest.mark.asyncio
async def test_prepare_rejects_an_empty_file(monkeypatch, tmp_path):
    """The single choke point every ingestion path goes through."""
    empty = tmp_path / "notes.txt"
    empty.write_bytes(b"")
    processor = _processor(monkeypatch, _resource(empty))

    with pytest.raises(InvalidArgumentError) as excinfo:
        await processor.prepare(str(empty))

    assert "notes.txt" in str(excinfo.value)
    assert "empty" in str(excinfo.value)


@pytest.mark.asyncio
async def test_an_empty_remote_download_is_rejected_too(monkeypatch, tmp_path):
    """A URL whose body turns out to be empty is refused at fetch time."""
    downloaded = tmp_path / "tmp9f3a21"
    downloaded.write_bytes(b"")
    resource = _resource(
        downloaded,
        source_type=SourceType.HTTP,
        original_filename="quarterly-report.pdf",
    )
    processor = _processor(monkeypatch, resource)

    with pytest.raises(InvalidArgumentError) as excinfo:
        await processor.prepare("https://example.com/quarterly-report.pdf")

    # The caller's own filename, not the temp working copy.
    assert "quarterly-report.pdf" in str(excinfo.value)
    assert "tmp9f3a21" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_one_byte_file_is_still_accepted(monkeypatch, tmp_path):
    """Only zero bytes is refused; this is not a minimum-size policy."""
    tiny = tmp_path / "tiny.txt"
    tiny.write_bytes(b"x")
    processor = _processor(monkeypatch, _resource(tiny))

    assert await processor.prepare(str(tiny)) is not None


@pytest.mark.asyncio
async def test_a_directory_source_is_not_treated_as_empty(monkeypatch, tmp_path):
    """Repository and folder imports containing empty files still work."""
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "__init__.py").write_bytes(b"")
    processor = _processor(monkeypatch, _resource(directory))

    assert await processor.prepare(str(directory)) is not None


def test_a_missing_source_is_left_to_the_normal_path(tmp_path):
    """A vanished source is reported by the normal path, not by this check."""
    UnifiedResourceProcessor._reject_empty_resource(_resource(tmp_path / "gone.txt"), None)


def test_a_stat_race_does_not_surface_here(tmp_path):
    """is_file() then stat() is not atomic; a race must not raise here."""
    racing = tmp_path / "racing.txt"
    racing.write_bytes(b"")

    class _RacingPath(type(racing)):
        def stat(self, *args, **kwargs):
            raise OSError("file vanished between is_file() and stat()")

    UnifiedResourceProcessor._reject_empty_resource(_resource(_RacingPath(racing)), None)


def test_the_error_is_a_400_for_http_callers():
    """The raised error must map to 400, not 500, at the HTTP boundary."""

    class _ZeroByteFile(type(Path("/"))):
        def __new__(cls):
            return super().__new__(cls, "/notes.txt")

        def is_file(self):
            return True

        def stat(self, *args, **kwargs):
            return SimpleNamespace(st_size=0)

    with pytest.raises(InvalidArgumentError) as excinfo:
        UnifiedResourceProcessor._reject_empty_resource(_resource(_ZeroByteFile()), None)

    assert ERROR_CODE_TO_HTTP_STATUS[excinfo.value.code] == 400


def test_an_explicit_source_name_wins_over_the_resolved_one(tmp_path):
    """The caller's declared name is the one they will recognise."""
    empty = tmp_path / "tmp0001"
    empty.write_bytes(b"")
    resource = _resource(empty, resolved_name="resolved.txt", original_filename="orig.txt")

    with pytest.raises(InvalidArgumentError) as excinfo:
        UnifiedResourceProcessor._reject_empty_resource(resource, "declared.txt")

    assert "declared.txt" in str(excinfo.value)
