import pytest
from conftest import rules_in

from dnsrules.unbound.domain import InvalidDomain
from dnsrules.unbound.zone import (
    REFRESH,
    RIGHT_HAND_SIDE,
    Action,
    Record,
    header,
    render,
)


def test_header_carries_the_serial_and_the_refresh():
    text = header(7)
    assert "@ SOA localhost. root.localhost. 7 " in text
    assert f" {REFRESH} " in text
    assert "@ NS localhost." in text


def test_header_is_the_worst_case_for_a_lost_transfer():
    """unbound refetches on this interval, so a lost trigger costs an hour."""
    assert REFRESH == 3600


def test_render_writes_one_line_per_rule():
    text = render(
        [
            Record("b.example.com", Action.BLOCK),
            Record("a.example.com", Action.ALLOW),
        ],
        1,
    )
    assert rules_in(text) == [
        "a.example.com CNAME rpz-passthru.",
        "b.example.com CNAME .",
    ]
    assert text.endswith("\n")


def test_render_is_stable_for_the_same_rules_and_serial():
    records = [Record("example.com", Action.BLOCK)]
    assert render(records, 3) == render(records, 3)


def test_render_changes_when_the_serial_changes():
    """A serial that does not rise leaves unbound with what it already has."""
    records = [Record("example.com", Action.BLOCK)]
    assert render(records, 3) != render(records, 4)


def test_render_with_no_rules_returns_the_header_alone():
    assert render([], 1) == header(1)


def test_render_normalizes_and_sorts():
    text = render(
        [Record("B.example.com.", Action.BLOCK), Record("a.EXAMPLE.com", Action.BLOCK)],
        1,
    )
    assert rules_in(text) == ["a.example.com CNAME .", "b.example.com CNAME ."]


def test_render_refuses_a_fused_line():
    """The fault this guards: a lost newline joins two rules into one.

    `rpz-passthru.example.com` is a legal CNAME target, so unbound loads the
    line, takes the transfer without complaint, and inverts the intent. The
    only defence is refusing the input.
    """
    fused = "google-analytics.com CNAME rpz-passthru.example.com"
    with pytest.raises(InvalidDomain):
        render([Record(fused, Action.ALLOW)], 1)


def test_render_refuses_a_domain_carrying_a_newline():
    with pytest.raises(InvalidDomain):
        render([Record("example.com\nevil.com CNAME .", Action.ALLOW)], 1)


def test_render_refuses_two_rules_for_one_domain():
    with pytest.raises(ValueError, match="more than one rule"):
        render(
            [Record("example.com", Action.BLOCK), Record("example.com.", Action.ALLOW)],
            1,
        )


def test_render_refuses_an_action_outside_the_table():
    """The type checker stops this. Render stops it again at runtime."""
    smuggled = Record("example.com", "CNAME evil.com.")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError):
        render([smuggled], 1)


def test_every_action_has_exactly_one_right_hand_side():
    assert set(RIGHT_HAND_SIDE) == set(Action)
    assert sorted(RIGHT_HAND_SIDE.values()) == [
        "CNAME .",
        "CNAME rpz-passthru.",
    ]
