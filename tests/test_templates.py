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
