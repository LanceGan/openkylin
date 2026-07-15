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
