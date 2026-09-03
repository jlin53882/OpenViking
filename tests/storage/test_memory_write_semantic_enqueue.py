# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Tests for semantic enqueue in _write_memory_with_refresh.

Verifies that memory writes now trigger semantic processing to generate
L0 directory abstracts (.abstract.md files), fixing Issue #2797.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_write_memory_enqueues_semantic_refresh():
    """Memory writes should trigger semantic refresh via _enqueue_semantic_refresh_changes."""
    from openviking.storage.content_write import ContentWriteOperator

    # Create mock operator
    operator = ContentWriteOperator.__new__(ContentWriteOperator)
    operator._viking_fs = AsyncMock()
    operator._vikingdb = AsyncMock()

    # Mock pathlock
    operator._viking_fs._uri_to_path.return_value = "/fake/path"
    operator._viking_fs._async_agfs = AsyncMock()
    lease = MagicMock()
    operator._viking_fs._async_agfs.pathlock_acquire_exact = AsyncMock(return_value=lease)
    operator._viking_fs._async_agfs.pathlock_release = AsyncMock()

    # Mock write_in_place
    operator._write_in_place = AsyncMock()

    # Mock MemoryUpdater methods
    with patch("openviking.storage.content_write.MemoryUpdater") as MockMU:
        MockMU.refresh_schema_overview = AsyncMock(return_value=True)
        MockMU.refresh_file_embedding = AsyncMock(return_value=True)
        MockMU.memory_type_from_uri.return_value = "event"

        # Mock _enqueue_semantic_refresh_changes
        operator._enqueue_semantic_refresh_changes = AsyncMock(return_value="REFRESH_NOW")

        # Mock _memory_vector_status
        operator._memory_vector_status.return_value = "requested"

        # Mock _build_write_result
        operator._build_write_result.return_value = {"status": "ok"}

        # Mock _vikingdb_has_queue
        operator._vikingdb_has_queue.return_value = False

        # Execute
        ctx = MagicMock()
        ctx.account_id = "default"
        ctx.user = MagicMock()
        ctx.user.user_id = "home"

        result = await operator._write_memory_with_refresh(
            uri="viking://user/home/memories/events/mem_test.md",
            root_uri="viking://user/home/memories/events",
            content="test content",
            mode="create",
            wait=False,
            timeout=30.0,
            ctx=ctx,
            written_bytes=12,
            telemetry_id="test-telemetry",
        )

        # Verify semantic refresh was called
        operator._enqueue_semantic_refresh_changes.assert_called_once()
        call_kwargs = operator._enqueue_semantic_refresh_changes.call_args
        assert call_kwargs.kwargs["root_uri"] == "viking://user/home/memories/events"
        assert call_kwargs.kwargs["context_type"] == "memory"
        assert "added" in call_kwargs.kwargs["changes"]


@pytest.mark.asyncio
async def test_write_memory_semantic_failure_doesnt_block():
    """Semantic enqueue failure should not block the memory write."""
    from openviking.storage.content_write import ContentWriteOperator

    operator = ContentWriteOperator.__new__(ContentWriteOperator)
    operator._viking_fs = AsyncMock()
    operator._vikingdb = AsyncMock()

    operator._viking_fs._uri_to_path.return_value = "/fake/path"
    operator._viking_fs._async_agfs = AsyncMock()
    lease = MagicMock()
    operator._viking_fs._async_agfs.pathlock_acquire_exact = AsyncMock(return_value=lease)
    operator._viking_fs._async_agfs.pathlock_release = AsyncMock()

    operator._write_in_place = AsyncMock()

    with patch("openviking.storage.content_write.MemoryUpdater") as MockMU:
        MockMU.refresh_schema_overview = AsyncMock(return_value=True)
        MockMU.refresh_file_embedding = AsyncMock(return_value=True)
        MockMU.memory_type_from_uri.return_value = "event"

        # Semantic refresh fails
        operator._enqueue_semantic_refresh_changes = AsyncMock(
            side_effect=Exception("Queue manager not available")
        )
        operator._memory_vector_status.return_value = "skipped"
        operator._build_write_result.return_value = {"status": "ok"}
        operator._vikingdb_has_queue.return_value = False

        ctx = MagicMock()
        ctx.account_id = "default"
        ctx.user = MagicMock()
        ctx.user.user_id = "home"

        # Should not raise
        result = await operator._write_memory_with_refresh(
            uri="viking://user/home/memories/events/mem_test.md",
            root_uri="viking://user/home/memories/events",
            content="test content",
            mode="create",
            wait=False,
            timeout=30.0,
            ctx=ctx,
            written_bytes=12,
            telemetry_id="test-telemetry",
        )

        assert result == {"status": "ok"}
