#!/usr/bin/env python3
"""Make CoreDNS use UDP first when its upstream does not support DNS/TCP."""

from __future__ import annotations

import argparse
import re
import sys


_FORWARD_LINE = re.compile(
    r"^(?P<indent>\s*)forward\s+\.\s+/etc/resolv\.conf(?P<block>\s*\{\s*)?$"
)


def ensure_prefer_udp(corefile: str) -> str:
    """Return a Corefile with one guarded upstream forward block."""
    lines = corefile.splitlines()
    matches = [index for index, line in enumerate(lines) if _FORWARD_LINE.match(line)]
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one 'forward . /etc/resolv.conf' directive"
        )

    index = matches[0]
    match = _FORWARD_LINE.match(lines[index])
    assert match is not None
    indent = match.group("indent")

    if match.group("block"):
        closing_index = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if lines[candidate].strip() == "}"
                and len(lines[candidate]) - len(lines[candidate].lstrip()) == len(indent)
            ),
            None,
        )
        if closing_index is None:
            raise ValueError("CoreDNS forward block is not closed")
        if any(
            line.strip() == "prefer_udp"
            for line in lines[index + 1 : closing_index]
        ):
            return corefile
        lines.insert(closing_index, f"{indent}    prefer_udp")
    else:
        lines[index : index + 1] = [
            f"{indent}forward . /etc/resolv.conf {{",
            f"{indent}    prefer_udp",
            f"{indent}}}",
        ]

    suffix = "\n" if corefile.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _self_test() -> None:
    single_line = ".:53 {\n    forward . /etc/resolv.conf\n}\n"
    expected = (
        ".:53 {\n"
        "    forward . /etc/resolv.conf {\n"
        "        prefer_udp\n"
        "    }\n"
        "}\n"
    )
    assert ensure_prefer_udp(single_line) == expected
    assert ensure_prefer_udp(expected) == expected

    existing_block = (
        ".:53 {\n"
        "    forward . /etc/resolv.conf {\n"
        "        max_fails 3\n"
        "    }\n"
        "}\n"
    )
    updated = ensure_prefer_udp(existing_block)
    assert "        max_fails 3\n        prefer_udp\n" in updated
    assert ensure_prefer_udp(updated) == updated

    try:
        ensure_prefer_udp(".:53 {\n    cache 30\n}\n")
    except ValueError:
        pass
    else:
        raise AssertionError("missing forward directive was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("CoreDNS prefer_udp transformer self-test passed.")
        return 0

    source = sys.stdin.read()
    try:
        rendered = ensure_prefer_udp(source)
    except ValueError as exc:
        print(f"CoreDNS configuration rejected: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if rendered != source:
            print("CoreDNS prefer_udp is not configured", file=sys.stderr)
            return 1
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
