import re
from pathlib import Path

import pytest

import dnsrules

TEMPLATES = sorted(Path(dnsrules.__file__).parent.rglob("*.html"))


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda path: path.name)
def test_no_comment_spans_more_than_one_line(path):
    """`{# #}` is single line only. Django prints a two line one to the page.

    Use `{% comment %}` for anything longer.
    """
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if "{#" in line:
            assert "#}" in line, f"{path}:{number} opens a comment it never closes"


STYLESHEET = Path(dnsrules.__file__).parent / "static" / "dnsrules" / "app.css"


def defined_classes() -> set[str]:
    return set(re.findall(r"\.([a-z][a-z0-9-]*)\s*[,{]", STYLESHEET.read_text()))


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda path: path.name)
def test_every_class_a_template_uses_is_defined(path):
    """There is no build step to catch a class that styles nothing.

    Tailwind generated a rule for whatever a template named, so a typo was
    invisible. A hand written stylesheet cannot do that, so check it here.
    """
    used = {
        word
        for value in re.findall(r'class="([^"{}]*)"', path.read_text())
        for word in value.split()
    }
    assert used <= defined_classes(), f"{path.name} uses undefined classes"
