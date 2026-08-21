"""อ่าน "วันที่และเวลา" จากใบเสร็จ

★ ทำไมต้องมี:
    วันที่ใช้ 2 อย่าง — กันใบซ้ำ (ใบเดียวกันวันเดียวกัน) และกันใบเก่าเกิน
    ถ้าอ่านผิด ระบบจะมองใบเดียวกันเป็นคนละใบ → ลูกค้าได้แต้มซ้ำ

★ กฎสำคัญที่สุด: วันที่ต้อง "เป็นไปได้จริง"
    เจอของจริง: ระบบเคยอ่านได้ปี 2069 เพราะไปหยิบข้อความแนวตั้งข้างสลิปธนาคาร
    ที่เขียนว่า "SFSL 120-9 (VAT) (1-01/69)" มาตีความเป็นวันที่ 1/01/69
    → ใบเสร็จจากอนาคต 43 ปี ควรถูกปฏิเสธตั้งแต่ต้น
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

#: ปีไทย (พ.ศ.) มากกว่าปีสากลอยู่ 543
_BUDDHIST_YEAR_OFFSET = 543
_BUDDHIST_YEAR_THRESHOLD = 2400

#: ช่วงปีที่ยอมรับ — ใบเสร็จจากอนาคตหรือเก่ากว่านี้คือ OCR อ่านมั่ว
_MAX_YEARS_AHEAD = 1
_MAX_YEARS_BEHIND = 5

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "ม.ค": 1, "ก.พ": 2, "มี.ค": 3, "เม.ย": 4, "พ.ค": 5, "มิ.ย": 6,
    "ก.ค": 7, "ส.ค": 8, "ก.ย": 9, "ต.ค": 10, "พ.ย": 11, "ธ.ค": 12,
}

#: 06/06/2026 · 06-06-69 · 6.6.2026
#:
#: ★ ตัวคั่นสองตัวต้องเป็นอักขระเดียวกัน (backreference \2) — วันที่จริงไม่มีทางผสม
#:   เจอจริง: "SFSL 120-9 (VAT) (1-01/69)" ข้างสลิปธนาคาร ถูกอ่านเป็นวันที่ 1/01/69
#:   เพราะยอมให้ "-" กับ "/" ปนกันได้ → ระบบได้วันที่มั่วจากข้อความที่ไม่ใช่วันที่เลย
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})([/\-.])(\d{1,2})\2(\d{2,4})(?!\d)")

#: "Jun 6, 2026" · "6 Jun 2026" — สลิปธนาคารใช้รูปแบบนี้
_MONTH_FIRST = re.compile(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})\s*,?\s*(\d{4})\b", re.IGNORECASE)
_DAY_FIRST = re.compile(r"\b(\d{1,2})\s+([a-z]{3})[a-z]*\.?\s*,?\s*(\d{4})\b", re.IGNORECASE)

#: 17:25:14 · 5:45 PM · "18 15 08" (เครื่องพิมพ์บางรุ่นใช้ช่องว่างแทนทวิภาค)
#:
#: ★ ตัวบอกช่วงเช้า/บ่ายจับแค่ตัวอักษรแรก (a/p) แล้วปล่อยตัวที่สองเป็นอะไรก็ได้
#:   เพราะ OCR อ่าน "PM" เพี้ยนเป็น "PH"/"PN" บ่อยมากบนกระดาษความร้อน
#:   ถ้าไม่รับ ระบบจะได้ 05:25 แทนที่จะเป็น 17:25 (คลาด 12 ชั่วโมง)
_TIME_COLON = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap])[a-z]?\b", re.IGNORECASE)
_TIME_COLON_PLAIN = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)")
_TIME_SPACED = re.compile(r"(?<!\d)(\d{2})\s(\d{2})\s(\d{2})(?!\d)")

#: "181508" — ทวิภาคหายหมด (เจอจริงบนสลิปธนาคาร: "Jun 6, 2026 181508")
#: ⚠ ใช้เฉพาะบรรทัดที่มีวันที่อยู่ด้วยเท่านั้น — ไม่งั้นจะไปจับรหัสอย่าง "STAN#071650"
#:   มาเป็นเวลา 07:16:50 (เลข 6 หลักบนใบเสร็จส่วนใหญ่เป็นรหัส ไม่ใช่เวลา)
_TIME_COMPACT = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")


#: คำที่บอกว่าบรรทัดนี้พูดถึงวันที่จริงๆ (ไม่ใช่ตัวเลขที่บังเอิญหน้าตาเหมือนวันที่)
_DATE_KEYWORDS = ("date", "วันที่", "วัน")


def find_date(lines: list[str], *, today: date | None = None) -> date | None:
    """วันที่บนใบเสร็จ · ไม่เจอ/ไม่สมเหตุสมผล → None

    ★ เก็บผู้สมัครทุกตัวก่อนแล้วค่อยเลือก — ไม่ใช่เอาตัวแรกที่เจอ
      เพราะใบเสร็จมีตัวเลขหน้าตาเหมือนวันที่เต็มไปหมด (รหัสสาขา, เลขที่ภาษี,
      ข้อความแนวตั้งข้างสลิป) การเอาตัวแรกทำให้ได้ของผิดบ่อย

    ลำดับความน่าเชื่อถือ:
        1. มีชื่อเดือนกำกับ ("Jun 6, 2026")  — OCR อ่านเพี้ยนแล้วยังเดาผิดยากที่สุด
        2. อยู่ในบรรทัดที่มีคำว่า date/วันที่
        3. เจอซ้ำหลายที่ในใบเดียวกัน (ใบเสร็จมักพิมพ์วันที่มากกว่าหนึ่งจุด)
    """
    today = today or date.today()
    candidates: list[tuple[int, date]] = []

    for line in lines:
        has_keyword = any(word in line.lower() for word in _DATE_KEYWORDS)

        from_name = _from_month_name(line)
        if from_name and _is_plausible(from_name, today):
            candidates.append((10 + (3 if has_keyword else 0), from_name))
            continue

        from_numeric = _from_numeric(line)
        if from_numeric and _is_plausible(from_numeric, today):
            candidates.append((5 + (3 if has_keyword else 0), from_numeric))

    if not candidates:
        return None

    # นับว่าวันไหนโผล่ซ้ำกี่ครั้ง — ยิ่งซ้ำยิ่งน่าเชื่อ
    repeats = {value: sum(1 for _, other in candidates if other == value) for _, value in candidates}
    best_score, best_date = max(candidates, key=lambda item: (item[0], repeats[item[1]]))
    return best_date


def find_time(lines: list[str]) -> time | None:
    """เวลาบนใบเสร็จ · ไม่เจอ → None

    ใช้คู่กับวันที่เพื่อระบุ "ธุรกรรมนี้" ให้แม่นขึ้น — ร้านเดียวกัน วันเดียวกัน
    ยอดเท่ากัน แต่คนละเวลา = คนละครั้ง (กันการปฏิเสธแต้มผิดๆ ว่าเป็นใบซ้ำ)
    """
    for line in lines:
        # บรรทัดที่มีวันที่อยู่ด้วย = น่าเชื่อที่สุดว่าเลขข้างๆ คือเวลาของธุรกรรม
        has_date = _from_month_name(line) is not None or _from_numeric(line) is not None

        found = (
            _time_from_colon(line)
            or _time_from_spaces(line)
            or (_time_compact(line) if has_date else None)
        )
        if found:
            return found
    return None


# ═══════════════════════════════════════════
# วันที่
# ═══════════════════════════════════════════

def _from_month_name(line: str) -> date | None:
    for pattern, order in ((_MONTH_FIRST, "md"), (_DAY_FIRST, "dm")):
        match = pattern.search(line)
        if not match:
            continue

        raw_month = match.group(1 if order == "md" else 2).lower()[:3]
        month = _MONTH_NAMES.get(raw_month)
        if month is None:
            continue

        day = int(match.group(2 if order == "md" else 1))
        return _build(int(match.group(3)), month, day)
    return None


def _from_numeric(line: str) -> date | None:
    match = _NUMERIC_DATE.search(line)
    if not match:
        return None

    # group 2 คือตัวคั่น (ใช้ backreference) — ข้ามไป เอาแค่ตัวเลข
    day, month, year = int(match.group(1)), int(match.group(3)), int(match.group(4))
    return _build(year, month, day)


def _build(year: int, month: int, day: int) -> date | None:
    if year < 100:
        # ปี 2 หลัก: 26 → 2026 · 69 (พ.ศ.) → 2569 → 2026
        year += 2500 if year > 50 else 2000
    if year > _BUDDHIST_YEAR_THRESHOLD:
        year -= _BUDDHIST_YEAR_OFFSET

    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None  # 32/13 — OCR อ่านเลขเพี้ยน


def _is_plausible(value: date, today: date) -> bool:
    """ใบเสร็จต้องอยู่ในช่วงเวลาที่เป็นไปได้จริง

    กันเคสที่ระบบไปหยิบตัวเลขอื่นบนใบเสร็จมาตีความเป็นวันที่
    (เจอจริง: "1-01/69" จากข้อความแนวตั้งข้างสลิป → ปี 2069)
    """
    return (
        value.year <= today.year + _MAX_YEARS_AHEAD
        and value.year >= today.year - _MAX_YEARS_BEHIND
    )


# ═══════════════════════════════════════════
# เวลา
# ═══════════════════════════════════════════

def _time_from_colon(line: str) -> time | None:
    # ลองแบบมี AM/PM ก่อน — ถ้ามีตัวบอกช่วง ต้องใช้ ไม่งั้นคลาด 12 ชั่วโมง
    for pattern, has_meridiem in ((_TIME_COLON, True), (_TIME_COLON_PLAIN, False)):
        for match in pattern.finditer(line):
            hour, minute = int(match.group(1)), int(match.group(2))
            second = int(match.group(3) or 0)

            if has_meridiem:
                meridiem = match.group(4).lower()
                if meridiem == "p" and hour < 12:
                    hour += 12
                elif meridiem == "a" and hour == 12:
                    hour = 0

            if _valid_clock(hour, minute, second):
                return time(hour, minute, second)
    return None


def _time_compact(line: str) -> time | None:
    """"181508" → 18:15:08 (ทวิภาคหายหมด)"""
    for match in _TIME_COMPACT.finditer(line):
        hour, minute, second = (int(part) for part in match.groups())
        if _valid_clock(hour, minute, second):
            return time(hour, minute, second)
    return None


def _time_from_spaces(line: str) -> time | None:
    """"18 15 08" — เครื่องพิมพ์บางรุ่นพิมพ์ทวิภาคจางจน OCR อ่านเป็นช่องว่าง"""
    for match in _TIME_SPACED.finditer(line):
        hour, minute, second = (int(part) for part in match.groups())
        if _valid_clock(hour, minute, second):
            return time(hour, minute, second)
    return None


def _valid_clock(hour: int, minute: int, second: int) -> bool:
    return 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59
