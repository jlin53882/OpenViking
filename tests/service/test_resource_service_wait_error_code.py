# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Typed failures from queued resource jobs must survive ``wait=True``."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openviking.server.identity import RequestContext, Role
from openviking.service import resource_service as resource_service_module
from openviking.service.resource_service import ResourceService
from openviking.service.task_tracker import TaskStatus
from openviking_cli.session.user_id import UserIdentifier


@pytest.mark.asyncio
async def test_waited_resource_failure_preserves_public_error_code(monkeypatch):
    service = ResourceService(
        vikingdb=object(),
        viking_fs=object(),
        resource_processor=object(),
        skill_processor=object(),
    )
    service._connector_delegate = SimpleNamespace(
        should_delegate=lambda *args, **kwargs: False,
    )
    service._prepare_standard_source_plan = AsyncMock(return_value=object())
    service._enqueue_source_plan = AsyncMock(
        return_value={"status": "success", "task_id": "task-1"}
    )

    tracker = SimpleNamespace(
        wait=AsyncMock(
            return_value=SimpleNamespace(
                status=TaskStatus.FAILED,
                error="'remote-empty.txt' is empty (0 bytes)",
                result={"code": "INVALID_ARGUMENT"},
            )
        )
    )
    monkeypatch.setattr(
        "openviking.service.task_tracker.get_task_tracker",
        lambda: tracker,
    )
    monkeypatch.setattr(
        "openviking.connector.delegate.detect_connector_add_type",
        lambda _path: None,
    )
    monkeypatch.setattr(resource_service_module, "is_git_repo_url", lambda _path: False)

    result = await service.add_resource(
        path="https://example.com/remote-empty.txt",
        ctx=RequestContext(
            user=UserIdentifier("account-1", "user-1"),
            role=Role.USER,
        ),
        to="viking://resources/remote-empty.txt",
        wait=True,
    )

    assert result == {
        "status": "error",
        "code": "INVALID_ARGUMENT",
        "errors": ["'remote-empty.txt' is empty (0 bytes)"],
    }
