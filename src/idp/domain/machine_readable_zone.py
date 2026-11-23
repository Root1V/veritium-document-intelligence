"""The machine-readable line of ID cards and passports (ICAO 9303, VRT-116):
its check digits confirm the document number, birth and expiry dates without
a model. Read from the OCR text by the platform, never written by the agent.

Only the data line of TD2 cards (36 characters) and TD3 passports (44) is
read: it alone carries the number and both dates. A TD1 card (3 lines of 30)
needs its lines paired and no type of the catalog carries one yet."""

from __future__ import annotations

import re

from pydantic import BaseModel

from idp.parsing.normalize import ParsedDocument

_WEIGHTS = (7, 3, 1)


def check_digit(field: str) -> int:
    def value(c: str) -> int:
        return 0 if c == "<" else int(c) if c.isdigit() else ord(c) - 55

    return sum(value(c) * _WEIGHTS[i % 3] for i, c in enumerate(field)) % 10


class MachineReadableZone(BaseModel):
    line: str
    page: int | None = None
    number: str
    birth: str  # YYMMDD
    expiry: str  # YYMMDD
    failed: list[str] = []  # check digits that do not match: number, birth, expiry, composite


def _ok(field: str, digit: str) -> bool:
    return digit.isdigit() and check_digit(field) == int(digit)


def parse_line(text: str, page: int | None = None) -> MachineReadableZone | None:
    """A TD2 or TD3 data line: number and its digit, nationality, birth and its
    digit, sex, expiry and its digit, optional data, composite digit."""
    line = re.sub(r"\s", "", text).upper()
    if len(line) not in (36, 44) or not re.fullmatch(r"[A-Z0-9<]+", line) or not re.fullmatch(r"\d{12}", line[13:19] + line[21:27]):
        return None
    optional_end = 35 if len(line) == 36 else 43
    checks = {
        "number": _ok(line[0:9], line[9]),
        "birth": _ok(line[13:19], line[19]),
        "expiry": _ok(line[21:27], line[27]),
        "composite": _ok(line[0:10] + line[13:20] + line[21:optional_end], line[-1]),
    }
    return MachineReadableZone(
        line=line, page=page, number=line[0:9].rstrip("<"), birth=line[13:19], expiry=line[21:27], failed=[k for k, ok in checks.items() if not ok]
    )


def find_zones(parsed: ParsedDocument) -> list[MachineReadableZone]:
    return [z for b in parsed.blocks if "<" in b.text and (z := parse_line(b.text, b.page)) is not None]
