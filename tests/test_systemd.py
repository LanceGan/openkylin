from uuid import UUID

import pytest

from kylinbootlab.systemd import (
    parse_duration_ns,
    parse_systemd_blame,
    parse_systemd_time,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("500ms", 500_000_000),
        ("1.250s", 1_250_000_000),
        ("1min 2.500s", 62_500_000_000),
        ("250us", 250_000),
    ],
)
def test_parse_duration_ns(value: str, expected: int) -> None:
    assert parse_duration_ns(value) == expected


def test_parse_systemd_time_excludes_firmware_and_loader() -> None:
    output = (
        "Startup finished in 2.000s (firmware) + 1.000s (loader) + "
        "3.000s (kernel) + 500ms (initrd) + 4.000s (userspace) = 10.500s\n"
        "graphical.target reached after 3.250s in userspace.\n"
    )

    metrics = parse_systemd_time(RUN_ID, output)

    assert metrics.kernel_ns == 3_000_000_000
    assert metrics.initrd_ns == 500_000_000
    assert metrics.userspace_ns == 4_000_000_000
    assert metrics.os_total_ns == 7_500_000_000
    assert metrics.graphical_target_from_t0_ns == 6_750_000_000


def test_parse_systemd_blame_ranks_units() -> None:
    units = parse_systemd_blame(
        "1min 2.500s slow.service\n900ms NetworkManager.service\n250ms dbus.service\n"
    )

    assert [unit.unit for unit in units] == [
        "slow.service",
        "NetworkManager.service",
        "dbus.service",
    ]
    assert units[0].rank == 1
    assert units[0].duration_ns == 62_500_000_000


def test_parse_duration_rejects_unknown_text() -> None:
    with pytest.raises(ValueError, match="invalid systemd duration"):
        parse_duration_ns("about one second")


def test_parse_duration_rejects_partial_match() -> None:
    with pytest.raises(ValueError, match="invalid systemd duration"):
        parse_duration_ns("500ms garbage")


def test_parse_systemd_time_without_graphical_target() -> None:
    output = "Startup finished in 1.000s (kernel) + 2.000s (userspace) = 3.000s\n"

    metrics = parse_systemd_time(RUN_ID, output)

    assert metrics.kernel_ns == 1_000_000_000
    assert metrics.initrd_ns == 0
    assert metrics.userspace_ns == 2_000_000_000
    assert metrics.graphical_target_from_t0_ns is None


def test_parse_systemd_time_without_initrd() -> None:
    output = (
        "Startup finished in 3.000s (kernel) + 4.000s (userspace) = 7.000s\n"
        "graphical.target reached after 3.250s in userspace.\n"
    )

    metrics = parse_systemd_time(RUN_ID, output)

    assert metrics.initrd_ns == 0
    assert metrics.os_total_ns == 7_000_000_000
    assert metrics.graphical_target_from_t0_ns == 6_250_000_000


def test_parse_systemd_blame_empty_output() -> None:
    units = parse_systemd_blame("")

    assert units == []


def test_parse_systemd_blame_whitespace_only() -> None:
    units = parse_systemd_blame("   \n  \n  ")

    assert units == []


def test_parse_systemd_blame_template_units() -> None:
    units = parse_systemd_blame(
        "1.250s foo@bar.service\n500ms systemd-journald.service\n"
    )

    assert len(units) == 2
    assert units[0].unit == "foo@bar.service"


def test_parse_systemd_time_rejects_missing_startup_line() -> None:
    with pytest.raises(ValueError, match="no startup line"):
        parse_systemd_time(RUN_ID, "some other output\n")


def test_parse_systemd_time_rejects_missing_kernel() -> None:
    output = "Startup finished in 2.000s (userspace) = 2.000s\n"

    with pytest.raises(ValueError, match="kernel and userspace"):
        parse_systemd_time(RUN_ID, output)
