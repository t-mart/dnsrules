import pytest

from dnsrules.unbound.domain import InvalidDomain
from dnsrules.unbound.zone import (
    FALLBACK_HEADER,
    RIGHT_HAND_SIDE,
    Action,
    Record,
    read_header,
    render,
    write,
)

# Copied from the "Create the runtime rules zone if absent" task in mace's
# playbook.yml. That task runs once, with force: false.
ANSIBLE_ZONE = """\
$TTL 3600
@ SOA localhost. root.localhost. 1 14400 3600 86400 3600
  NS  localhost.

; Runtime state. Ansible creates this file once and never rewrites it.
; This zone is read first, so a rule here beats every other RPZ zone.
;
; Format:
; <domain> CNAME rpz-passthru.   ; ignore the blocklist
; <domain> CNAME .               ; block, answer NXDOMAIN
"""


@pytest.fixture
def zone_path(tmp_path):
    path = tmp_path / "rpz-runtime-rules.zone"
    path.write_text(ANSIBLE_ZONE)
    return path


def rules_of(text):
    header = read_header_of(text)
    return [line for line in text[len(header) :].splitlines() if line.strip()]


def read_header_of(text):
    marker = "\n; <domain> CNAME .               ; block, answer NXDOMAIN\n"
    return text[: text.index(marker) + len(marker)]


def test_read_header_keeps_the_soa_and_the_comments(zone_path):
    header = read_header(zone_path)
    assert "@ SOA localhost. root.localhost. 1 14400 3600 86400 3600" in header
    assert "  NS  localhost." in header
    assert "; Format:" in header
    # A comment that looks like a rule is still a comment.
    assert "; <domain> CNAME rpz-passthru." in header


def test_read_header_falls_back_when_the_file_is_absent(tmp_path):
    assert read_header(tmp_path / "missing.zone") == FALLBACK_HEADER


def test_read_header_stops_at_the_first_rule(zone_path):
    zone_path.write_text(f"{ANSIBLE_ZONE}\nexample.com CNAME .\n; trailing\n")
    header = read_header(zone_path)
    assert "; Format:" in header
    assert "example.com" not in header
    assert "; trailing" not in header


def test_render_writes_one_line_per_rule(zone_path):
    text = render(
        [
            Record("b.example.com", Action.BLOCK),
            Record("a.example.com", Action.ALLOW),
            Record("c.example.com", Action.BLOCK_NODATA),
        ],
        read_header(zone_path),
    )
    assert rules_of(text) == [
        "a.example.com CNAME rpz-passthru.",
        "b.example.com CNAME .",
        "c.example.com CNAME *.",
    ]
    assert text.endswith("\n")


def test_render_is_stable_across_a_round_trip(zone_path):
    """Header in, header out. Rendering twice must not grow the file."""
    records = [Record("example.com", Action.BLOCK)]
    once = render(records, read_header(zone_path))
    write(zone_path, once)
    twice = render(records, read_header(zone_path))
    assert twice == once


def test_render_with_no_rules_returns_the_header_alone(zone_path):
    header = read_header(zone_path)
    assert render([], header) == header


def test_render_normalizes_and_sorts(zone_path):
    text = render(
        [Record("B.example.com.", Action.BLOCK), Record("a.EXAMPLE.com", Action.BLOCK)],
        read_header(zone_path),
    )
    assert rules_of(text) == ["a.example.com CNAME .", "b.example.com CNAME ."]


def test_render_refuses_a_fused_line(zone_path):
    """The fault seen on mace: a lost newline joins two rules into one.

    `rpz-passthru.example.com` is a legal CNAME target, so unbound loads the
    line, reloads without complaint, and inverts the intent. The only defence
    is refusing the input.
    """
    fused = "google-analytics.com CNAME rpz-passthru.example.com"
    with pytest.raises(InvalidDomain):
        render([Record(fused, Action.ALLOW)], read_header(zone_path))


def test_render_refuses_a_domain_carrying_a_newline(zone_path):
    with pytest.raises(InvalidDomain):
        render(
            [Record("example.com\nevil.com CNAME .", Action.ALLOW)],
            read_header(zone_path),
        )


def test_render_refuses_two_rules_for_one_domain(zone_path):
    with pytest.raises(ValueError, match="more than one rule"):
        render(
            [Record("example.com", Action.BLOCK), Record("example.com.", Action.ALLOW)],
            read_header(zone_path),
        )


def test_render_refuses_an_action_outside_the_table(zone_path):
    """The type checker stops this. Render stops it again at runtime."""
    smuggled = Record("example.com", "CNAME evil.com.")  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError):
        render([smuggled], read_header(zone_path))


def test_every_action_has_exactly_one_right_hand_side():
    assert set(RIGHT_HAND_SIDE) == set(Action)
    assert sorted(RIGHT_HAND_SIDE.values()) == [
        "CNAME *.",
        "CNAME .",
        "CNAME rpz-passthru.",
    ]


def test_write_replaces_the_file_and_leaves_no_temporary(zone_path):
    write(zone_path, "hello\n")
    assert zone_path.read_text() == "hello\n"
    assert list(zone_path.parent.iterdir()) == [zone_path]


def test_write_sets_the_mode(zone_path):
    write(zone_path, "hello\n", mode=0o640)
    assert zone_path.stat().st_mode & 0o777 == 0o640


def test_write_keeps_the_old_file_when_it_fails(zone_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("dnsrules.unbound.zone.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        write(zone_path, "replacement\n")
    assert zone_path.read_text() == ANSIBLE_ZONE
    assert list(zone_path.parent.iterdir()) == [zone_path]
