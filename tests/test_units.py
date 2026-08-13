"""The shipped systemd units.

These files reach a router by copy, so nothing catches a typo in them there
except a failed boot. The checks here are cheap and they hold the units to the
commands that exist.
"""

import configparser

import pytest
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError

from dnsrules.core.management.commands.units import SOURCE, files

SYSTEMD = SOURCE / "systemd" / "system"
BINARY = "/usr/local/bin/dnsrules"

UNITS = sorted(path.name for path in SYSTEMD.glob("dnsrules-*"))
SERVICES = [name for name in UNITS if name.endswith(".service")]


class Unit(configparser.ConfigParser):
    """Keep the key case of the file, so a lookup here reads like the unit."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


def parse(path):
    # strict=False: a unit repeats a key on purpose, as ExecStart does in the
    # nightly unit. configparser keeps the last one, so read a repeated key
    # with lines() instead.
    parser = Unit(strict=False)
    parser.read_string(path.read_text())
    return parser


def lines(path, key: str) -> list[str]:
    """Every value of one key, in file order."""
    return [
        line.split("=", 1)[1]
        for line in path.read_text().splitlines()
        if line.startswith(f"{key}=")
    ]


def test_the_tree_holds_every_kind_of_file():
    names = {str(name) for name in files()}
    assert "sysusers.d/dnsrules.conf" in names
    assert "tmpfiles.d/dnsrules.conf" in names
    assert "systemd/system/unbound.service.d/dnsrules.conf" in names
    assert len(UNITS) == 7


@pytest.mark.parametrize("name", UNITS)
def test_a_unit_parses(name):
    assert parse(SYSTEMD / name).sections()


@pytest.mark.parametrize("name", SERVICES)
def test_a_service_runs_a_command_this_project_has(name):
    """A renamed management command must fail here, not on the router."""
    for line in lines(SYSTEMD / name, "ExecStart"):
        binary, command = line.split()[0], line.split()[1]
        assert binary == BINARY
        assert command in get_commands()


def test_the_nightly_unit_rolls_up_before_it_drops_a_partition():
    """A oneshot stops at the first failure, so this order keeps the day."""
    commands = [
        line.split()[1]
        for line in lines(SYSTEMD / "dnsrules-nightly.service", "ExecStart")
    ]
    assert commands == ["rollup", "partitions"]


@pytest.mark.parametrize("name", SERVICES)
def test_a_service_reads_the_environment_file(name):
    assert parse(SYSTEMD / name)["Service"]["EnvironmentFile"] == (
        "/etc/dnsrules/dnsrules.env"
    )


@pytest.mark.parametrize("name", SERVICES)
def test_a_service_runs_as_the_dnsrules_user(name):
    assert parse(SYSTEMD / name)["Service"]["User"] == "dnsrules"


@pytest.mark.parametrize("name", [n for n in UNITS if n.endswith(".timer")])
def test_a_timer_has_the_service_it_starts(name):
    """systemd matches a timer to a service by name alone."""
    assert (SYSTEMD / name.replace(".timer", ".service")).is_file()


def test_a_unit_that_writes_a_zone_file_may_write_there():
    """ProtectSystem=strict makes /etc read-only, so a reconcile needs this."""
    for name in ["dnsrules-web.service", "dnsrules-prune.service"]:
        assert (
            "/etc/unbound/rules" in parse(SYSTEMD / name)["Service"]["ReadWritePaths"]
        )


def test_output_copies_the_tree(tmp_path):
    call_command("units", "--output", tmp_path)
    assert (tmp_path / "systemd/system/dnsrules-web.service").is_file()
    assert (tmp_path / "sysusers.d/dnsrules.conf").is_file()
    assert (tmp_path / "systemd/system/unbound.service.d/dnsrules.conf").is_file()


def test_a_second_copy_stops_before_it_writes(tmp_path):
    call_command("units", "--output", tmp_path)
    (tmp_path / "systemd/system/dnsrules-web.service").write_text("edited")
    with pytest.raises(CommandError):
        call_command("units", "--output", tmp_path)
    assert (tmp_path / "systemd/system/dnsrules-web.service").read_text() == "edited"


def test_force_replaces_an_edited_file(tmp_path):
    call_command("units", "--output", tmp_path)
    (tmp_path / "systemd/system/dnsrules-web.service").write_text("edited")
    call_command("units", "--output", tmp_path, "--force")
    assert "ExecStart" in (tmp_path / "systemd/system/dnsrules-web.service").read_text()
