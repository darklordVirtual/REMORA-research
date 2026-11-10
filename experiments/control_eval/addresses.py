# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Find the addresses inside free text, and decide whether a task named them.

Used by the second plan-bound arm (``plan_flow.plan2_gate``): a web address,
an email address or an IBAN inside text the adversary may have written is a
target, and must be one the user's task names.

This is a floor, by construction. It finds addresses written as addresses.
What it finds, in order:

1. An address after a scheme (``https://``, ``ftp://``, any ``x://``) or after
   a leading ``//``. Any host counts, with or without a dot, and the path is
   kept. User information and the port are dropped.
2. An email address around each ``@``.
3. A bare host: ``www.`` anything, a dotted name under one of :data:`TLDS`,
   an IPv4 address, or a dotted name with a non-ASCII label (a homoglyph or
   an internationalised name is treated as an address, not as prose).
4. An IBAN by shape, compact or in groups, in either case. The check digits
   are not verified, so a serial number of that shape is found too.

Before searching, the text is NFKC-normalised, format characters (zero-width
joiners and the like) are removed, and the ideographic full stop becomes a
dot. Strings are taken from every leaf of a value and from mapping keys.

What it does not find, and no test claims otherwise: a bare host under a
top-level domain outside :data:`TLDS` (``evil.zone``; country codes that are
also file extensions, such as ``.py`` and ``.md``, are left out on purpose);
an address spelled in words ("example dot com"); one split across list
elements; one inside an image, an attachment or an encoding. It also finds
things that are not addresses to a reader: ``Booking.com`` and ``ASP.net``
in a sentence are hosts here.

Every search is linear in the text: single character classes, bounded
repeats and explicit scans around ``@``; no pattern can backtrack over a run.

:func:`named_by` is the comparison. It is by address, not by substring:
``doe@gmail.com`` is not named by a task that names ``john.doe@gmail.com``,
and ``evil.com`` is not named by ``not-evil.com``. A web address is named
when the task names the same host and the value adds no path of its own.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["TLDS", "Address", "find_addresses", "named_by"]

#: Top-level domains under which a bare dotted name is read as a host.
TLDS: Final = frozenset("""
com org net edu gov mil int info biz name pro io co ai app dev xyz top site online shop
store club link click live news tech cloud page blog zip mov ly me tv to gg fm
uk de fr nl be ch at no se dk fi es it pt ie eu ru ua cn jp kr in au nz ca us mx br ar za
""".split())

_SCHEME: Final = re.compile(r"""[A-Za-z][A-Za-z0-9+.\-]{0,15}://[^\s<>"'`]{1,2048}""")
_RELATIVE: Final = re.compile(r"""(?<![:\w/])//[^\s<>"'`/]{1,255}[^\s<>"'`]{0,2048}""")
_RUN: Final = re.compile(r"[\w.\-]+")
_PATH: Final = re.compile(r"""/[^\s<>"'`]{0,2048}""")
# Groups of four, then at most one shorter group, as IBANs are written. A
# word of exactly four characters right after a grouped IBAN is taken as one
# more group; a shorter or longer word is not.
_IBAN: Final = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}[0-9]{2}(?:[ \-]?[A-Za-z0-9]{4}){2,7}"
                          r"(?:[ \-]?[A-Za-z0-9]{1,3})?(?![A-Za-z0-9])")
_TRAILING: Final = ".,;:!?)]}*_~|\\"
_LOCAL_EXTRA: Final = frozenset("._%+-")
_MAX_SIDE: Final = 254


@dataclass(frozen=True, order=True)
class Address:
    kind: str   # "web", "email" or "iban"
    key: str    # normalised form, the one compared
    text: str   # as found

    def __str__(self) -> str:
        return self.key


def _strings(value: Any) -> Iterable[str]:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, (bytes, bytearray)):
        yield bytes(value).decode("latin-1")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _strings(item)
    else:
        yield str(value)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u3002", ".")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _host_labels(host: str) -> list[str] | None:
    labels = host.split(".")
    if len(labels) < 2 or any(not label or label[0] == "-" or label[-1] == "-"
                              or not all(ch.isalnum() or ch == "-" for ch in label)
                              for label in labels):
        return None
    return labels


def _is_ipv4(labels: list[str]) -> bool:
    return len(labels) == 4 and all(label.isdigit() and len(label) <= 3 and int(label) <= 255
                                    for label in labels)


def _bare_host(host: str) -> bool:
    labels = _host_labels(host)
    if labels is None:
        return False
    if _is_ipv4(labels) or labels[0].lower() == "www":
        return True
    last = labels[-1]
    if not last.isalpha() or len(last) < 2:
        return False
    if any(not label.isascii() for label in labels):
        return True
    # "plan.No more": a capitalised word after a full stop is a new sentence.
    if last != last.lower() and last != last.upper():
        return False
    return last.lower() in TLDS


def _web_key(host: str, path: str) -> str:
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    path = path.rstrip(_TRAILING + "/")
    return host + path


def _from_url(rest: str) -> tuple[str, str] | None:
    """``(host, path)`` of what follows a scheme, or None."""
    cut = len(rest)
    for mark in "/?#":
        at = rest.find(mark)
        if at >= 0:
            cut = min(cut, at)
    authority, path = rest[:cut], rest[cut:]
    authority = authority.rpartition("@")[2]
    if authority.startswith("["):
        host = authority[1:].partition("]")[0]
    else:
        host = authority.partition(":")[0]
    host = host.strip(_TRAILING)
    return (host, path) if host else None


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """*text* with every span replaced by spaces, so a later search cannot see it."""
    if not spans:
        return text
    chars = list(text)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    return "".join(chars)


def _emails(text: str, found: set[Address], taken: list[tuple[int, int]]) -> None:
    at = text.find("@")
    while at >= 0:
        left = at
        while left > 0 and at - left < _MAX_SIDE and (
                text[left - 1].isalnum() or text[left - 1] in _LOCAL_EXTRA):
            left -= 1
        right = at + 1
        while right < len(text) and right - at <= _MAX_SIDE and (
                text[right].isalnum() or text[right] in ".-"):
            right += 1
        local = text[left:at].strip("".join(_LOCAL_EXTRA))
        domain = text[at + 1:right].strip(".-")
        labels = _host_labels(domain)
        if local and labels is not None and labels[-1].isalpha():
            found.add(Address("email", f"{local.lower()}@{domain.lower()}", f"{local}@{domain}"))
            taken.append((left, right))
        at = text.find("@", at + 1)


def _hosts(text: str, found: set[Address]) -> None:
    for match in _RUN.finditer(text):
        offset = match.start()
        for piece in match.group().split("_"):
            piece_start, offset = offset, offset + len(piece) + 1
            host = piece.strip(".-")
            if not host or not _bare_host(host):
                continue
            host_end = piece_start + len(piece.rstrip(".-")) if piece.rstrip(".-") else piece_start
            path = ""
            if host_end < len(text) and text[host_end] == "/" and host_end == piece_start + len(piece):
                path = _PATH.match(text, host_end).group()  # type: ignore[union-attr]
            found.add(Address("web", _web_key(host, path), host + path.rstrip(_TRAILING)))


def find_addresses(value: Any) -> list[Address]:
    """Every address in the strings of *value*, sorted and without repeats."""
    found: set[Address] = set()
    for raw in _strings(value):
        text = _normalise(raw)
        taken: list[tuple[int, int]] = []
        for pattern, skip in ((_SCHEME, None), (_RELATIVE, 2)):
            for match in pattern.finditer(text):
                rest = match.group()
                rest = rest[skip:] if skip else rest.partition("://")[2]
                parsed = _from_url(rest)
                if parsed is None:
                    continue
                host, path = parsed
                found.add(Address("web", _web_key(host, path), (host + path).rstrip(_TRAILING)))
                taken.append(match.span())
        # Each kind is blanked out once found, so the next search cannot read
        # part of it as something else, and no search rescans another's spans.
        text, taken = _blank(text, taken), []
        for match in _IBAN.finditer(text):
            compact = re.sub(r"[ \-]", "", match.group()).upper()
            if 15 <= len(compact) <= 34:
                found.add(Address("iban", compact, match.group()))
                taken.append(match.span())
        text, taken = _blank(text, taken), []
        _emails(text, found, taken)
        _hosts(_blank(text, taken), found)
    unique: dict[tuple[str, str], Address] = {}
    for address in sorted(found):
        unique.setdefault((address.kind, address.key), address)
    return list(unique.values())


def named_by(address: Address, task_addresses: Iterable[Address],
             own: Iterable[str] = ()) -> bool:
    """Whether the task, or the principal's own identifiers, name *address*."""
    own_keys = {str(o).lower() for o in own}
    if address.key.lower() in own_keys:
        return True
    same_kind = [t for t in task_addresses if t.kind == address.kind]
    if address.kind != "web":
        return any(t.key == address.key for t in same_kind)
    host, slash, path = address.key.partition("/")
    for t in same_kind:
        t_host, _, t_path = t.key.partition("/")
        if t_host == host and (not slash or path == t_path):
            return True
    return False
