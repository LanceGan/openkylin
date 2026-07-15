import re
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import NonNegativeInt

from kylinbootlab.contracts import ContractModel

_TOKEN = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>min|ms|us|s)")
_PHASE = re.compile(r"^(?P<duration>.+?) \((?P<phase>[^)]+)\)$")
_BLAME = re.compile(
    r"^\s*(?P<duration>(?:\d+(?:\.\d+)?(?:min|ms|us|s)\s*)+)\s+"
    r"(?P<unit>\S+)\s*$"
)
_FACTORS = {
    "min": Decimal(60_000_000_000),
    "s": Decimal(1_000_000_000),
    "ms": Decimal(1_000_000),
    "us": Decimal(1_000),
}


class BootMetrics(ContractModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    kernel_ns: NonNegativeInt
    initrd_ns: NonNegativeInt
    userspace_ns: NonNegativeInt
    os_total_ns: NonNegativeInt
    graphical_target_from_t0_ns: NonNegativeInt | None


class UnitTiming(ContractModel):
    rank: int
    unit: str
    duration_ns: NonNegativeInt


def parse_duration_ns(text: str) -> int:
    total = Decimal(0)
    consumed: list[tuple[int, int]] = []
    for match in _TOKEN.finditer(text):
        total += Decimal(match.group("value")) * _FACTORS[match.group("unit")]
        consumed.append(match.span())

    remainder = list(text)
    for start, end in consumed:
        remainder[start:end] = " " * (end - start)
    if not consumed or "".join(remainder).strip():
        raise ValueError(f"invalid systemd duration: {text}")
    return int(total)


def parse_systemd_time(run_id: UUID, output: str) -> BootMetrics:
    startup = next(
        (line for line in output.splitlines() if line.startswith("Startup finished in ")),
        None,
    )
    if startup is None:
        raise ValueError("systemd-analyze output has no startup line")

    phase_text = startup.removeprefix("Startup finished in ").split(" = ", maxsplit=1)[0]
    phases: dict[str, int] = {}
    for segment in phase_text.split(" + "):
        match = _PHASE.fullmatch(segment.strip())
        if match is None:
            raise ValueError(f"invalid systemd startup phase: {segment}")
        phases[match.group("phase")] = parse_duration_ns(match.group("duration"))

    if "kernel" not in phases or "userspace" not in phases:
        raise ValueError("systemd startup output must contain kernel and userspace phases")
    initrd_ns = phases.get("initrd", 0)
    pre_userspace_ns = phases["kernel"] + initrd_ns

    graphical_target_ns: int | None = None
    graphical = re.search(
        r"^graphical\.target reached after (?P<duration>.+?) in userspace\.$",
        output,
        flags=re.MULTILINE,
    )
    if graphical is not None:
        graphical_target_ns = pre_userspace_ns + parse_duration_ns(graphical.group("duration"))

    return BootMetrics(
        run_id=run_id,
        kernel_ns=phases["kernel"],
        initrd_ns=initrd_ns,
        userspace_ns=phases["userspace"],
        os_total_ns=pre_userspace_ns + phases["userspace"],
        graphical_target_from_t0_ns=graphical_target_ns,
    )


def parse_systemd_blame(output: str) -> list[UnitTiming]:
    parsed: list[tuple[str, int]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        match = _BLAME.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid systemd blame line: {line}")
        parsed.append((match.group("unit"), parse_duration_ns(match.group("duration"))))

    parsed.sort(key=lambda item: item[1], reverse=True)
    return [
        UnitTiming(rank=index, unit=unit, duration_ns=duration_ns)
        for index, (unit, duration_ns) in enumerate(parsed, start=1)
    ]
