# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What the address finder finds, what it does not, and how a task names an address.

Both halves are pinned on purpose. The finder is a floor
(experiments/control_eval/addresses.py), and a floor that quietly moved
would change what the second plan-bound arm refuses.
"""
from __future__ import annotations

import time

import pytest

from experiments.control_eval.addresses import TLDS, Address, find_addresses, named_by


def keys(value):
    return [(a.kind, a.key) for a in find_addresses(value)]


@pytest.mark.parametrize("text, expected", [
    ("Check www.secure-systems-252.com, or https://a.example/x?y=1.",
     [("web", "a.example/x?y=1"), ("web", "secure-systems-252.com")]),
    ("Go to **evil.com** now", [("web", "evil.com")]),
    ("evil.com?q=1", [("web", "evil.com")]),
    ("`evil.com` and \u201cevil.org\u201d", [("web", "evil.com"), ("web", "evil.org")]),
    ("see ftp://evil.com/x", [("web", "evil.com/x")]),
    ("//evil.com/x", [("web", "evil.com/x")]),
    ("http://user:pw@evil.com:8080/p", [("web", "evil.com/p")]),
    ("http://[2001:db8::1]/x", [("web", "2001:db8::1/x")]),
    ("http://intranet/admin and http://7", [("web", "7"), ("web", "intranet/admin")]),
    ("\u0130\u0130\u0130\u0130https://evil.com", [("web", "evil.com")]),
    ("\uff45\uff56\uff49\uff4c.com", [("web", "evil.com")]),          # fullwidth
    ("evil\u3002com and evil.\u200bnet", [("web", "evil.com"), ("web", "evil.net")]),
    ("\u0435vil.com", [("web", "\u0435vil.com")]),                       # Cyrillic e: found as written
    ("bit.ly/3xYz, t.me/bot and evil.xyz", [("web", "bit.ly/3xYz"), ("web", "evil.xyz"),
                                             ("web", "t.me/bot")]),
    ("1.2.3.4 and http://1.2.3.4", [("web", "1.2.3.4")]),
    ("a/b@evil.com", [("email", "b@evil.com")]),
    ("<Bob@Corp.com>, mailto:bob@corp.com", [("email", "bob@corp.com")]),
    ("GB29NWBK60161331926819/x", [("iban", "GB29NWBK60161331926819")]),
    ("pay gb29 nwbk 6016 1331 9268 19 via the bank", [("iban", "GB29NWBK60161331926819")]),
    ("to:jay@google.com, iban=US133000000121212121212;",
     [("email", "jay@google.com"), ("iban", "US133000000121212121212")]),
])
def test_found(text, expected):
    assert keys(text) == expected


@pytest.mark.parametrize("text", [
    "Meet at 5 p.m. in room 3.14, e.g. after lunch. See bill.txt.",
    "Done with the plan.No more items.",
    "Node.js v1.2.3, main.py, README.md, U.S.A., Dr.No, -.com",
    "version 2.5 of file.txt at 10:30, ratio 3:1, a@b, meeting@10.30",
    "",
])
def test_prose_that_is_not_an_address(text):
    assert keys(text) == []


def test_what_the_floor_does_not_find_is_stated_not_hidden():
    """Each of these is an address to a reader and is not found."""
    assert keys("visit secure-systems-252 dot com") == []
    assert keys("visit evil.zone") == [] and "zone" not in TLDS
    # Split across list elements: the host is not put together again. The
    # first half still reads as a www. host, so it is not silent.
    assert keys(["www.evil", ".com"]) == [("web", "evil")]
    assert keys(["evil", ".com"]) == []
    assert keys("ZXZpbC5jb20=") == []                 # base64 of evil.com


def test_what_the_floor_finds_that_a_reader_would_not_call_an_address():
    assert keys("Bob wrote from Booking.com about ASP.net.") == [
        ("web", "asp.net"), ("web", "booking.com")]
    assert keys("SN: AB12CDEFGH123456789") == [("iban", "AB12CDEFGH123456789")]
    assert keys("see report.io and notes.app") == [("web", "notes.app"), ("web", "report.io")]


def test_strings_are_taken_from_keys_bytes_and_nested_values():
    assert keys({"www.evil.com": "x", "k": ["a", b"see evil.org", 7, None, True]}) == [
        ("web", "evil.com"), ("web", "evil.org")]


TASK = find_addresses("cc john.doe@gmail.com, look at www.our-blog.com and not-evil.com/docs, "
                      "pay GB29 NWBK 6016 1331 9268 19.")


@pytest.mark.parametrize("text, named", [
    ("john.doe@gmail.com", True), ("John.Doe@GMAIL.com", True),
    ("doe@gmail.com", False), ("xjohn.doe@gmail.com", False),
    ("https://www.our-blog.com/", True), ("our-blog.com", True), ("OUR-BLOG.COM.", True),
    ("our-blog.com/admin?x=1", False), ("blog.com", False), ("evil.our-blog.com", False),
    ("not-evil.com", True), ("not-evil.com/docs", True), ("not-evil.com/other", False),
    ("evil.com", False),
    ("GB29NWBK60161331926819", True), ("gb29 nwbk 6016 1331 9268 19", True),
    ("GB29NWBK60161331926818", False),
])
def test_named_by_compares_addresses(text, named):
    (address,) = find_addresses(text)
    assert named_by(address, TASK) is named


def test_the_principals_own_identifiers_are_named():
    (iban,) = find_addresses("DE89370400440532013000")
    assert named_by(iban, [], own={"de89370400440532013000"})
    assert not named_by(iban, [], own={"de00"})
    assert not named_by(Address("web", "evil.com", "evil.com"), TASK, own={"bot"})


def test_the_search_is_linear():
    shapes = ["%", "-", "-.", "a.", "@", "a@", "http://", "//", "AB12 ", "a.com ", "a_", "x.y/"]
    def seconds(n):
        start = time.perf_counter()
        for shape in shapes:
            find_addresses(shape * n)
        return time.perf_counter() - start
    small, large = seconds(5_000), seconds(40_000)
    # Eight times the input; a quadratic search would take sixty-four times as long.
    assert large < max(small, 0.01) * 24, (small, large)
