"""Tests for interactive prompt helpers."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ouroboros.cli.formatters.prompting import multiline_prompt_async


@pytest.mark.asyncio
async def test_multiline_prompt_async_patches_stdout_and_stderr() -> None:
    """The shared prompt helper should proxy both stdout and stderr during input."""
    session = MagicMock()
    session.prompt_async = AsyncMock()

    async def fake_prompt_async() -> str:
        assert sys.stdout is not sys.__stdout__
        assert sys.stderr is not sys.__stderr__
        return "line 1\nline 2"

    session.prompt_async.side_effect = fake_prompt_async

    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    fake_stdout = MagicMock()
    fake_stdout.isatty.return_value = True

    with (
        patch(
            "ouroboros.cli.formatters.prompting.PromptSession", return_value=session
        ) as mock_session,
        patch("ouroboros.cli.formatters.prompting.console.print"),
        patch("ouroboros.cli.formatters.prompting.sys.stdin", fake_stdin),
        patch("ouroboros.cli.formatters.prompting.sys.stdout", fake_stdout),
    ):
        result = await multiline_prompt_async("Prompt here")

    assert result == "line 1\nline 2"
    session.prompt_async.assert_awaited_once()

    kwargs = mock_session.call_args.kwargs
    assert kwargs["message"] == "> "
    assert kwargs["multiline"] is True
    assert kwargs["prompt_continuation"] == "  "

    key_bindings = kwargs["key_bindings"]
    bound_keys = {tuple(binding.keys) for binding in key_bindings.bindings}
    assert ("c-j",) in bound_keys
    assert ("c-m",) in bound_keys


@pytest.mark.asyncio
async def test_multiline_prompt_async_falls_back_without_tty() -> None:
    """Non-TTY transports should bypass prompt_toolkit instead of crashing."""
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = False
    fake_stdout = MagicMock()
    fake_stdout.isatty.return_value = False

    with (
        patch("ouroboros.cli.formatters.prompting.sys.stdin", fake_stdin),
        patch("ouroboros.cli.formatters.prompting.sys.stdout", fake_stdout),
        patch("ouroboros.cli.formatters.prompting.console.print"),
        patch(
            "ouroboros.cli.formatters.prompting._fallback_line_input",
            new=AsyncMock(return_value="plain answer\n"),
        ) as fallback_mock,
        patch("ouroboros.cli.formatters.prompting.PromptSession") as prompt_session,
    ):
        result = await multiline_prompt_async("Prompt here")

    assert result == "plain answer"
    fallback_mock.assert_awaited_once()
    prompt_session.assert_not_called()
