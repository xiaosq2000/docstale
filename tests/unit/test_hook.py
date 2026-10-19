from __future__ import annotations

import json

import pytest

from docstale.hook import HookInputError, parse_context


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{", "invalid hook JSON"),
        ("[]", "must be a JSON object"),
        ('{"cwd": "/repo", "stop_hook_active": false}', "missing `session_id`"),
        ('{"session_id": "one", "stop_hook_active": false}', "missing `cwd`"),
    ],
)
def test_rejects_missing_or_invalid_shared_fields(raw: str, message: str) -> None:
    with pytest.raises(HookInputError, match=message):
        parse_context(raw)


@pytest.mark.parametrize("event", ["SessionStart", "Stop", None])
def test_parses_supported_events(event: str | None) -> None:
    payload: dict[str, object] = {"session_id": "one", "cwd": "/repo"}
    if event is not None:
        payload["hook_event_name"] = event
    if event != "SessionStart":
        payload["stop_hook_active"] = False
    context = parse_context(json.dumps(payload))
    assert context.hook_event_name == (event or "Stop")
    assert context.stop_hook_active is False


@pytest.mark.parametrize("event", ["PostToolUse", None, 1, {}, []])
def test_rejects_unsupported_events(event: object) -> None:
    with pytest.raises(HookInputError, match="hook_event_name"):
        parse_context(json.dumps({"hook_event_name": event}))


@pytest.mark.parametrize("active", [None, "false", 0])
def test_stop_requires_boolean_continuation_flag(active: object) -> None:
    with pytest.raises(HookInputError, match="stop_hook_active"):
        parse_context(
            json.dumps(
                {
                    "session_id": "one",
                    "cwd": "/repo",
                    "stop_hook_active": active,
                }
            )
        )
