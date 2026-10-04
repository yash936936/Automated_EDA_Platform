"""
Phase 1.3 PII pre-scan (D-007): deterministic, regex-only, narrow on purpose.
Detects emails, phone numbers and national-ID patterns (Aadhaar, PAN, US SSN).
Names / free-text PII need NER and are deferred to v2.

Fed row by row from the same single streaming pass that computes dataset
metadata (storage.probe_dataset), so scanning costs no extra read of the file.

Findings are per (column, detector) and NEVER contain the matched values.

Confidence is a documented HEURISTIC, not a calibrated probability:
    confidence = reliability * (0.5 + 0.5 * min(1, match_rate / 0.5)) + header_boost
A single hit in a big column still reaches ~0.5 for precise detectors (so it
gets flagged -- D-003: flagging is cheap), while a column that is mostly
matches approaches the detector's reliability (so it can clear the 0.90
auto-mask bar in Phase 3.2). Collision-prone detectors also need a minimum
match rate, so random 10/12-digit IDs don't light up. Phase 8.2 is where
these numbers get validated against real data.
"""
import os
import re
from dataclasses import dataclass, field

FLAG_THRESHOLD = 0.40  # D-003: low bar to flag. (Auto-mask at 0.90 is Phase 3.2's job.)
HEADER_BOOST = 0.10


# ---------------- validators ----------------
_VD = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],
       [4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],
       [8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_VP = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
       [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]
_VINV = [0,4,3,2,1,5,6,7,8,9]


def verhoeff_valid(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(digits: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VD[c][_VP[(i + 1) % 8][int(ch)]]
    return str(_VINV[c])


# ---------------- patterns ----------------
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,})")
_NOT_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico", "bmp"}
_SSN = re.compile(r"(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}")
_PAN = re.compile(r"[A-Z]{5}\d{4}[A-Z]")
_PAN_HOLDER = set("PCHFATBLJG")  # 4th letter = holder type
_AADHAAR_FMT = re.compile(r"[2-9]\d{3}[ -]\d{4}[ -]\d{4}")
_AADHAAR_BARE = re.compile(r"[2-9]\d{11}")
_PHONE_INTL = re.compile(r"\+\d[\d\s().-]{6,20}\d")
_PHONE_NANP = re.compile(r"(?:\+?1[\s.-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[\s.-]?[2-9]\d{2}[\s.-]\d{4}")
_PHONE_IN_FMT = re.compile(r"[6-9]\d{4}[\s-]\d{5}")
_PHONE_IN_BARE = re.compile(r"(?:\+91[\s-]?|0)?[6-9]\d{9}")


@dataclass(frozen=True)
class Detector:
    name: str
    pii_type: str
    reliability: float
    min_rate: float          # below this match rate the column is NOT flagged
    hint_min_rate: float     # ...or this, when the header name also hints at the type
    hint_re: re.Pattern


_H_EMAIL = re.compile(r"e-?mail", re.I)
_H_PHONE = re.compile(r"phone|mobile|cell|contact|\btel\b|msisdn", re.I)
_H_AADHAAR = re.compile(r"aadhaa?r|\buid\b", re.I)
_H_PAN = re.compile(r"\bpan\b|pan[_ ]?(no|num|card)", re.I)
_H_SSN = re.compile(r"\bssn\b|social[_ ]?sec", re.I)

DETECTORS = {d.name: d for d in [
    Detector("email", "email", 0.98, 0.0, 0.0, _H_EMAIL),
    Detector("phone_formatted", "phone", 0.85, 0.0, 0.0, _H_PHONE),
    Detector("phone_bare", "phone", 0.55, 0.5, 0.2, _H_PHONE),
    Detector("aadhaar", "national_id", 0.97, 0.0, 0.0, _H_AADHAAR),
    Detector("aadhaar_bare", "national_id", 0.90, 0.5, 0.2, _H_AADHAAR),
    Detector("pan", "national_id", 0.95, 0.0, 0.0, _H_PAN),
    Detector("ssn", "national_id", 0.80, 0.0, 0.0, _H_SSN),
]}


def detect(value: str) -> list[str]:
    """Detector names that match one cell. Cheap length/shape gates first so a
    wide table doesn't pay for every regex on every cell."""
    v = value.strip()
    n = len(v)
    if n < 5:
        return []
    out = []
    if "@" in v:
        for m in _EMAIL.finditer(v):
            if m.group(1).lower() not in _NOT_TLDS:
                out.append("email")
                break
    if 7 <= n <= 30:
        c = v[0]
        if c == "+" or c == "(" or c.isdigit():
            digits = re.sub(r"\D", "", v)
            if _SSN.fullmatch(v):
                out.append("ssn")
            if _AADHAAR_FMT.fullmatch(v) and verhoeff_valid(digits):
                out.append("aadhaar")
            elif _AADHAAR_BARE.fullmatch(v) and verhoeff_valid(v):
                out.append("aadhaar_bare")
            if (
                (v[0] == "+" and _PHONE_INTL.fullmatch(v) and 8 <= len(digits) <= 15)
                or _PHONE_NANP.fullmatch(v)
                or _PHONE_IN_FMT.fullmatch(v)
            ):
                out.append("phone_formatted")
            elif _PHONE_IN_BARE.fullmatch(v):
                out.append("phone_bare")
        elif n == 10 and _PAN.fullmatch(v) and v[3] in _PAN_HOLDER:
            out.append("pan")
    return out


@dataclass
class Finding:
    column_index: int
    column_name: str
    detector: str
    pii_type: str
    match_count: int
    scanned_values: int
    match_rate: float
    confidence: float
    header_hint: bool


@dataclass
class PiiScanner:
    max_rows: int = field(default_factory=lambda: int(os.environ.get("PII_MAX_ROWS", "500000")))
    header: list[str] = field(default_factory=list)
    rows_scanned: int = 0
    rows_seen: int = 0
    _nonempty: dict = field(default_factory=dict)
    _hits: dict = field(default_factory=dict)  # (col, detector) -> count

    def set_header(self, fields: list[str]) -> None:
        self.header = [f.lstrip("\ufeff").strip() for f in fields]

    @property
    def truncated(self) -> bool:
        return self.rows_seen > self.rows_scanned

    def add_row(self, fields: list[str]) -> None:
        self.rows_seen += 1
        if self.rows_scanned >= self.max_rows:
            return
        self.rows_scanned += 1
        for i, cell in enumerate(fields):
            if not cell or cell.isspace():
                continue
            self._nonempty[i] = self._nonempty.get(i, 0) + 1
            for det in detect(cell):
                self._hits[(i, det)] = self._hits.get((i, det), 0) + 1

    def findings(self) -> list[Finding]:
        out = []
        for (col, name), count in self._hits.items():
            det = DETECTORS[name]
            total = self._nonempty.get(col, 0)
            if total == 0:
                continue
            rate = count / total
            col_name = self.header[col] if col < len(self.header) and self.header[col] else f"col_{col}"
            hint = bool(det.hint_re.search(col_name))
            if rate < (det.hint_min_rate if hint else det.min_rate):
                continue
            conf = det.reliability * (0.5 + 0.5 * min(1.0, rate / 0.5)) + (HEADER_BOOST if hint else 0.0)
            conf = round(min(1.0, conf), 4)
            if conf < FLAG_THRESHOLD:
                continue
            out.append(Finding(col, col_name, name, det.pii_type, count, total, round(rate, 6), conf, hint))
        return sorted(out, key=lambda f: (-f.confidence, f.column_index, f.detector))


class PiiNotScanned(RuntimeError):
    pass


def require_pii_scanned(conn, dataset_id: str) -> None:
    """Call before building ANY LLM context from a dataset (Phase 2+). Only a
    completed scan passes: 'pending', 'skipped_unsupported' and
    'legacy_unscanned' all block, because 'we didn't look' is not 'clean'."""
    with conn.cursor() as cur:
        cur.execute("SELECT pii_status FROM datasets WHERE id = %s", (dataset_id,))
        row = cur.fetchone()
    if row is None:
        raise PiiNotScanned(f"dataset {dataset_id} not found")
    if row[0] != "scanned":
        raise PiiNotScanned(f"dataset {dataset_id} has pii_status={row[0]!r}; refusing to expose it to an LLM")
