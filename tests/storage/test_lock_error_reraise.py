# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Tests for LockAcquisitionError re-raise in _write_memory_directory_semantics.

Verifies that LockAcquisitionError is re-raised directly instead of being
wrapped in RuntimeError, allowing the outer handler to properly re-enqueue.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openviking.storage.errors import LockAcquisitionError
from openviking.storage.queuefs.semantic_processor import SemanticProcessor


def _make_mock_msg():
    """Create a mock SemanticMsg with proper attributes."""
    msg = MagicMock()
    msg.coalesce_key = ""
    msg.coalesce_version = 0
    msg.context_type = "memory"
    msg.propagate_to_parent = True
    msg.use_hierarchical_aggregation = False
    msg.uri = "viking://user/usr1/memories/entities"
    return msg


@pytest.mark.asyncio
async def test_lock_acquisition_error_is_reraised_not_wrapped():
    """LockAcquisitionError from write_abstract_overview should be
    re-raised directly by _write_memory_directory_semantics,
    not wrapped in RuntimeError."""
    processor = SemanticProcessor()

    # Create mock viking_fs with pathlock that raises LockAcquisitionError
    mock_viking_fs = AsyncMock()
    mock_viking_fs._async_agfs.pathlock_acquire_exact_batch = AsyncMock(
        side_effect=LockAcquisitionError("Lock held by another process")
    )

    # _write_memory_directory_semantics should re-raise LockAcquisitionError
    with pytest.raises(LockAcquisitionError) as exc_info:
        await processor._write_memory_directory_semantics(
            msg=_make_mock_msg(),
            viking_fs=mock_viking_fs,
            dir_uri="viking://user/usr1/memories/entities",
            overview="Test overview",
            abstract="Test abstract",
            ctx=MagicMock(),
            lock=None,
            total_entries=0,
            sampled_entries=0,
        )

    # Verify: exception is LockAcquisitionError, NOT RuntimeError
    assert isinstance(exc_info.value, LockAcquisitionError)
    assert "Lock held by another process" in str(exc_info.value)


@pytest.mark.asyncio
async def test_lock_error_not_caught_by_generic_exception():
    """LockAcquisitionError should NOT be caught by the generic
    except Exception handler and wrapped in RuntimeError."""
    processor = SemanticProcessor()

    # Create mock viking_fs with pathlock that raises LockAcquisitionError
    mock_viking_fs = AsyncMock()
    mock_viking_fs._async_agfs.pathlock_acquire_exact_batch = AsyncMock(
        side_effect=LockAcquisitionError("Lock contention")
    )

    # Verify: NOT a RuntimeError (which would mean it was incorrectly wrapped)
    with pytest.raises(LockAcquisitionError):
        await processor._write_memory_directory_semantics(
            msg=_make_mock_msg(),
            viking_fs=mock_viking_fs,
            dir_uri="viking://user/usr1/memories/entities",
            overview="Test overview",
            abstract="Test abstract",
            ctx=MagicMock(),
            lock=None,
            total_entries=0,
            sampled_entries=0,
        )
