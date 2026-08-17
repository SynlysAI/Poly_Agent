"""Assistant Slash Command 行解析器。"""

from __future__ import annotations

import re
from dataclasses import dataclass


COMMAND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class CommandParseError(ValueError):
    """表示输入不是合法命令或命令名为空。"""


@dataclass(frozen=True)
class ParsedCommand:
    """解析后的命令名和原样参数。"""

    name: str
    raw_args: str


def parse_command(line: str) -> ParsedCommand:
    """只解析行首 slash 命令，并保留名称后的原始参数。

    Args:
        line: 用户输入的一行文本。

    Returns:
        规范化为小写的命令名与原样 raw_args。

    Raises:
        CommandParseError: 输入不是行首 slash、命令名为空或名称非法。
    """
    text = str(line or "")
    if not text.lstrip().startswith("/"):
        raise CommandParseError("not_command")
    stripped = text.lstrip()
    body = stripped[1:]
    matched = re.match(r"\S+", body)
    if not matched:
        raise CommandParseError("empty_command_name")
    token = matched.group(0)
    name = token.lower()
    if not COMMAND_NAME_PATTERN.fullmatch(name):
        raise CommandParseError("invalid_command_name")
    raw_args = body[matched.end() :]
    return ParsedCommand(name=name, raw_args=raw_args)
