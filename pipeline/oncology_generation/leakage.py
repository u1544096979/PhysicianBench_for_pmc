from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_PREFIX_RE = re.compile(r"^(?:病理(?:提示|诊断(?:为)?|考虑|符合)|诊断(?:为)?|考虑|符合)[\s:：-]*")
_NON_DIAGNOSTIC_PREFIXES = ("结合临床", "建议", "请", "进一步", "待")


def diagnostic_fragments(value: object) -> tuple[str, ...]:
    """Return normalized diagnosis-bearing fragments from a target value."""
    fragments: list[str] = []
    for raw_fragment in _split_fragments(_normalize(value)):
        fragment = raw_fragment.strip()
        previous = None
        while fragment and fragment != previous:
            previous = fragment
            fragment = _PREFIX_RE.sub("", fragment, count=1).strip()
        if not fragment or fragment.startswith(_NON_DIAGNOSTIC_PREFIXES):
            continue
        cjk_count = sum("\u4e00" <= char <= "\u9fff" for char in fragment)
        ascii_count = sum(char.isascii() and char.isalnum() for char in fragment)
        if cjk_count >= 3 or ascii_count >= 4:
            if fragment not in fragments:
                fragments.append(fragment)
    return tuple(fragments)


def find_leaked_target_values(instruction: object, target_values: Iterable[object]) -> list[str]:
    """Return original target values with a diagnostic fragment in instruction."""
    normalized_instruction = _normalize(instruction)
    leaked: list[str] = []
    for target_value in target_values:
        original = str(target_value)
        if any(fragment in normalized_instruction for fragment in diagnostic_fragments(original)):
            if original not in leaked:
                leaked.append(original)
    return leaked


def _normalize(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value)).casefold()


def _split_fragments(value: str) -> list[str]:
    fragments: list[str] = []
    current: list[str] = []
    for char in value:
        if char.isspace() or unicodedata.category(char)[0] in {"P", "S"}:
            if current:
                fragments.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        fragments.append("".join(current))
    return fragments
