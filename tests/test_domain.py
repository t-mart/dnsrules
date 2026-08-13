import pytest

from dnsrules.unbound.domain import MAX_LENGTH, InvalidDomain, normalize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("example.com", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("  example.com  ", "example.com"),
        ("example.com.", "example.com"),
        ("*.example.com", "*.example.com"),
        ("a.b.c.example.com", "a.b.c.example.com"),
        ("xn--80ak6aa92e.com", "xn--80ak6aa92e.com"),
        ("1-2.example.com", "1-2.example.com"),
    ],
)
def test_normalize_accepts_a_domain(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        ".",
        "example",  # a bare label is not a domain
        "example.com..",
        ".example.com",
        "a..b.com",
        "-bad.example.com",
        "bad-.example.com",
        "*example.com",  # a wildcard needs its own label
        "a.*.example.com",
        "under_score.example.com",
        "exa mple.com",
        "http://example.com",
        f"{'a' * 64}.example.com",  # a label caps at 63
        ".".join(["aaaaaaaa"] * 32) + ".com",  # longer than MAX_LENGTH
    ],
)
def test_normalize_rejects_a_non_domain(text):
    with pytest.raises(InvalidDomain):
        normalize(text)


@pytest.mark.parametrize(
    "text",
    [
        "google-analytics.com CNAME rpz-passthru.",
        "example.com\nevil.com",
        "example.com\revil.com",
        "example.com\tCNAME .",
        "example.com CNAME rpz-passthru.example.com CNAME .",
    ],
)
def test_normalize_rejects_anything_carrying_a_second_field(text):
    """A domain never contains whitespace. This is what stops rule injection."""
    with pytest.raises(InvalidDomain):
        normalize(text)


def test_a_domain_at_the_length_limit_is_accepted():
    name = ".".join(["a" * 49] * 5)  # 5 * 49 + 4 == 249
    assert len(name) <= MAX_LENGTH
    assert normalize(name) == name
