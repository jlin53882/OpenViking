# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Tests for semantic enqueue in _write_memory_with_refresh.

Verifies that memory writes now trigger semantic processing to generate
L0 directory abstracts (.abstract.md files), fixing Issue #2797/#4612.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviking.storage.content_write import ContentWriteCoordinator


def _make_instance() -> ContentWriteCoordinator:
    """Create a ContentWriteCoordinator without calling __init__."""
    inst = ContentWriteCoordinator.__new__(ContentWriteCoordinator)
    # Attributes referenced by _write_memory_with_refresh body
    inst._vikingdb = None
    inst._viking_fs = None
    return inst


@pytest.mark.asyncio
async def test_write_memory_enqueues_semantic_refresh():
    """Memory writes should call _enqueue_semantic_refresh_changes."""
    inst = _make_instance()

    # Mock the viking_fs pathlock + write path
    inst._viking_fs = AsyncMock()
    inst._viking_fs._uri_to_path.return_value = "C:/fake/path"
    inst._viking_fs._async_agfs = AsyncMock()
    lease = MagicMock()
    inst._viking_fs._async_agfs.pathlock_acquire_exact = AsyncMock(return_value=lease)
    inst._viking_fs._async_agfs.pathlock_release = AsyncMock()
    inst._write_in_place = AsyncMock()

    # Patch MemoryUpdater classmethod side effects
    with patch("openviking.storage.content_write.MemoryUpdater") as mock_mu:
        mock_mu.refresh_schema_overview = AsyncMock(return_value=True)
        mock_mu.refresh_file_embedding = AsyncMock(return_value=True)
        mock_mu.memory_type_from_uri.return_value = "event"

        # Verify the semantic enqueue is invoked with correct args
        async def fake_enqueue(**kwargs):
            # Capture the call args via assertion on the real call below
            return "REFRESH_NOW"

        with patch.object(inst, "_enqueue_semantic_refresh_changes", side_effect=fake_enqueue) as mock_enqueue:
            with patch.object(inst, "_vikingdb_has_queue", return_value=False):
                with patch.object(inst, "_build_write_result", return_value={"status": "ok"}):
                    ctx = MagicMock()
                    ctx.account_id = "default"
                    ctx.user.user_id = "home"

                    result = await inst._write_memory_with_refresh(
                        uri="viking://user/home/memories/events/mem_test.md",
                        root_uri="viking://user/home/memories/events",
                        content="test",
                        mode="create",
                        wait=False,
                        timeout=30.0,
                        ctx=ctx,
                        written_bytes=4,
                        telemetry_id="test-tel",
                    )

                    assert result == {"status": "ok"}
                    # Semantic enqueue must have been called
                    mock_enqueue.assert_called_once()
                    kwargs = mock_enqueue.call_args.kwargs
                    assert kwargs["root_uri"] == "viking://user/home/memories/events"
                    assert kwargs["context_type"] == "memory"
                    assert "added" in kwargs["changes"]
                    assert "mem_test.md" in kwargs["changes"]["added"][0]


@pytest.mark.asyncio
async def test_write_memory_semantic_failure_does_not_block():
    """Semantic enqueue failure should not block the write."""
    inst = _make_instance()
    inst._viking_fs = AsyncMock()
    inst._viking_fs._uri_to_path.return_value = "C:/fake/path"
    inst._viking_fs._async_agfs = AsyncMock()
    lease = MagicMock()
    inst._viking_fs._async_agfs.pathlock_acquire_exact = AsyncMock(return_value=lease)
    inst._viking_fs._async_agfs.pathlock_release = AsyncMock()
    inst._write_in_place = AsyncMock()

    with patch("openviking.storage.content_write.MemoryUpdater") as mock_mu:
        mock_mu.refresh_schema_overview = AsyncMock(return_value=True)
        mock_mu.refresh_file_embedding = AsyncMock(return_value=True)
        mock_mu.memory_type_from_uri.return_value = "event"

        # Semantic enqueue raises
        with patch.object(
            inst, "_enqueue_semantic_refresh_changes",
            side_effect=RuntimeError("QueueManager not available"),
        ):
            with patch.object(inst, "_vikingdb_has_queue", return_value=False):
                with patch.object(inst, "_build_write_result", return_value={"status": "ok"}):
                    ctx = MagicMock()
                    ctx.account_id = "default"
                    ctx.user.user_id = "home"

                    # Should NOT raise (semantic enqueue failure swallowed)
                    result = await inst._write_memory_with_refresh(
                        uri="viking://user/home/memories/events/mem_test.md",
                        root_uri="viking://user/home/memories/events",
                        content="test",
                        mode="create",
                        wait=False,
                        timeout=30.0,
                        ctx=ctx,
                        written_bytes=4,
                        telemetry_id="test-tel",
                    )

                    assert result == {"status": "ok"}
