# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Tests for parent directory abstract rollup in _process_memory_directory.

Verifies that when a directory has only subdirectories (no .md files),
the processor collects child .abstract.md files and generates parent abstract.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviking.storage.queuefs.semantic_msg import SemanticMsg
from openviking.storage.queuefs.semantic_processor import SemanticProcessor


def _make_msg(uri="viking://user/usr1/memories", context_type="memory", **kwargs):
    """Build a minimal SemanticMsg for testing."""
    defaults = {
        "id": "test-msg-1",
        "uri": uri,
        "context_type": context_type,
        "recursive": False,
        "role": "root",
        "account_id": "acc1",
        "user_id": "usr1",
        "peer_id": "test-peer",
        "telemetry_id": "",
        "target_uri": "",
        "changes": None,
        "is_code_repo": False,
    }
    defaults.update(kwargs)
    return SemanticMsg.from_dict(defaults)


def _build_data(msg: SemanticMsg) -> dict:
    """Wrap a SemanticMsg into the dict format on_dequeue expects."""
    return msg.to_dict()


@pytest.mark.asyncio
async def test_parent_rollup_collects_child_abstracts():
    """When directory has only subdirectories, collect child .abstract.md files."""
    processor = SemanticProcessor()
    success = MagicMock()
    error_cb = MagicMock()
    processor.set_callbacks(success, error_cb, MagicMock())

    # Mock viking_fs to return only directories (no .md files)
    mock_viking_fs = AsyncMock()
    mock_viking_fs.ls.return_value = [
        {"name": "entities", "isDir": True},
        {"name": "cases", "isDir": True},
    ]

    # Mock read_file to return child abstracts
    async def mock_read_file(path, ctx=None):
        if "entities" in path:
            return "Entity abstract content"
        elif "cases" in path:
            return "Cases abstract content"
        return None

    mock_viking_fs.read_file = mock_read_file

    # Mock _write_memory_directory_semantics
    with patch.object(processor, "_write_memory_directory_semantics") as mock_write:
        mock_write.return_value = MagicMock(wrote=True)

        with patch("openviking.storage.queuefs.semantic_processor.get_viking_fs", return_value=mock_viking_fs):
            msg = _make_msg()
            data = _build_data(msg)

            await processor.on_dequeue(data)

            # Verify _write_memory_directory_semantics was called with parent abstract
            mock_write.assert_awaited_once()
            call_args = mock_write.call_args
            overview = call_args.kwargs.get("overview", "")
            assert "entities" in overview
            assert "cases" in overview


@pytest.mark.asyncio
async def test_parent_rollup_skips_placeholder_abstracts():
    """Skip child directories with placeholder abstracts."""
    processor = SemanticProcessor()
    success = MagicMock()
    error_cb = MagicMock()
    processor.set_callbacks(success, error_cb, MagicMock())

    # Mock viking_fs to return only directories
    mock_viking_fs = AsyncMock()
    mock_viking_fs.ls.return_value = [
        {"name": "entities", "isDir": True},
        {"name": "cases", "isDir": True},
    ]

    # Mock read_file to return placeholder for entities, real content for cases
    async def mock_read_file(path, ctx=None):
        if "entities" in path:
            return "# entities [Directory abstract is not ready]"
        elif "cases" in path:
            return "Cases abstract content"
        return None

    mock_viking_fs.read_file = mock_read_file

    # Mock _write_memory_directory_semantics
    with patch.object(processor, "_write_memory_directory_semantics") as mock_write:
        mock_write.return_value = MagicMock(wrote=True)

        with patch("openviking.storage.queuefs.semantic_processor.get_viking_fs", return_value=mock_viking_fs):
            msg = _make_msg()
            data = _build_data(msg)

            await processor.on_dequeue(data)

            # Verify only cases abstract was included (entities skipped)
            mock_write.assert_awaited_once()
            call_args = mock_write.call_args
            overview = call_args.kwargs.get("overview", "")
            assert "cases" in overview
            assert "entities" not in overview


@pytest.mark.asyncio
async def test_parent_rollup_handles_read_failure():
    """Handle read failure for one child without affecting others."""
    processor = SemanticProcessor()
    success = MagicMock()
    error_cb = MagicMock()
    processor.set_callbacks(success, error_cb, MagicMock())

    # Mock viking_fs to return only directories
    mock_viking_fs = AsyncMock()
    mock_viking_fs.ls.return_value = [
        {"name": "entities", "isDir": True},
        {"name": "cases", "isDir": True},
    ]

    # Mock read_file to fail for entities, succeed for cases
    async def mock_read_file(path, ctx=None):
        if "entities" in path:
            raise Exception("Read failed")
        elif "cases" in path:
            return "Cases abstract content"
        return None

    mock_viking_fs.read_file = mock_read_file

    # Mock _write_memory_directory_semantics
    with patch.object(processor, "_write_memory_directory_semantics") as mock_write:
        mock_write.return_value = MagicMock(wrote=True)

        with patch("openviking.storage.queuefs.semantic_processor.get_viking_fs", return_value=mock_viking_fs):
            msg = _make_msg()
            data = _build_data(msg)

            await processor.on_dequeue(data)

            # Verify only cases abstract was included (entities failed)
            mock_write.assert_awaited_once()
            call_args = mock_write.call_args
            overview = call_args.kwargs.get("overview", "")
            assert "cases" in overview
            assert "entities" not in overview
