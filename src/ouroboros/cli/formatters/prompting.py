"""Prompt helpers for interactive CLI input."""

from __future__ import annotations

import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.patch_stdout import patch_stdout

from ouroboros.cli.formatters import console


def _stdio_supports_prompt_toolkit() -> bool:
    """Return True when stdin/stdout are real TTYs suitable for prompt_toolkit."""
    stdin_isatty = getattr(sys.stdin, "isatty", None)
    stdout_isatty = getattr(sys.stdout, "isatty", None)
    return bool(callable(stdin_isatty) and stdin_isatty() and callable(stdout_isatty) and stdout_isatty())


async def _fallback_line_input() -> str:
    """Collect a single-line answer without prompt_toolkit when no TTY is present."""
    try:
        return await asyncio.to_thread(input, "> ")
    except EOFError:
        return ""


async def multiline_prompt_async(prompt_text: str) -> str:
    """Get multiline-safe input while allowing logs above the active prompt."""
    if not _stdio_supports_prompt_toolkit():
        console.print(f"[bold green]{prompt_text}[/] [dim](stdin is non-interactive; falling back to plain input)[/]")
        return (await _fallback_line_input()).rstrip("\n")

    bindings = KeyBindings()

    @bindings.add("c-j")
    def insert_newline(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("c-m")
    def submit(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    console.print(f"[bold green]{prompt_text}[/] [dim](Enter: submit, Ctrl+J: newline)[/]")

    session: PromptSession[str] = PromptSession(
        message="> ",
        multiline=True,
        prompt_continuation="  ",
        key_bindings=bindings,
    )

    # prompt_toolkit proxies both stdout and stderr above the prompt.
    with patch_stdout(raw=True):
        return await session.prompt_async()


__all__ = ["multiline_prompt_async"]
