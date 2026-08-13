import pytest
import yaml

from dnsrules.hosts import InvalidHosts, load


def write(path, data):
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_reads_the_groups(hosts_path):
    entries = load(hosts_path)
    assert set(entries.groups) == {"kids", "adults"}
    assert entries.groups["kids"].zone == "rules_kids"
    assert entries.groups["kids"].zonefile.name == "kids.zone"


def test_load_maps_each_address_to_a_host_name(hosts_path):
    entries = load(hosts_path)
    assert entries.names == {"10.0.0.2": "clove", "100.71.4.9": "clove"}
    assert entries.hosts[0].groups == ("kids",)


def test_a_missing_file_is_an_error_not_an_empty_result(tmp_path):
    """An empty result would render every zone file with no rules in it."""
    with pytest.raises(InvalidHosts, match="does not exist"):
        load(tmp_path / "missing.yml")


def test_bad_yaml_reports_the_path(tmp_path):
    path = tmp_path / "hosts.yml"
    path.write_text("groups: [\n  - name: kids\n unbalanced")
    with pytest.raises(InvalidHosts, match="not valid YAML"):
        load(path)


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ([{"zone": "z", "zonefile": "/f"}], "no name"),
        ([{"name": "kids", "zonefile": "/f"}], "no zone"),
        ([{"name": "kids", "zone": "z"}], "no zonefile"),
        (["kids"], "not an object"),
        (
            [
                {"name": "kids", "zone": "z", "zonefile": "/a"},
                {"name": "kids", "zone": "y", "zonefile": "/b"},
            ],
            "twice",
        ),
    ],
)
def test_a_group_needs_every_field(tmp_path, groups, message):
    path = write(tmp_path / "hosts.yml", {"groups": groups})
    with pytest.raises(InvalidHosts, match=message):
        load(path)


def test_a_zone_name_with_whitespace_is_refused(tmp_path):
    """The zone name becomes an argument to auth_zone_reload."""
    path = write(
        tmp_path / "hosts.yml",
        {"groups": [{"name": "kids", "zone": "a b", "zonefile": "/f"}]},
    )
    with pytest.raises(InvalidHosts, match="whitespace"):
        load(path)


def test_addresses_must_be_strings(tmp_path):
    path = write(
        tmp_path / "hosts.yml",
        {"hosts": [{"name": "clove", "addresses": [10]}]},
    )
    with pytest.raises(InvalidHosts, match="addresses"):
        load(path)


def test_a_file_with_no_groups_loads(tmp_path):
    entries = load(write(tmp_path / "hosts.yml", {"groups": [], "hosts": []}))
    assert entries.groups == {}
    assert entries.hosts == ()
