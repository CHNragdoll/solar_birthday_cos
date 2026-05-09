#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import sqlite3
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

LUNAR_MAX_YEAR = 2099
VALID_TAGS = ("生日", "重要事件", "纪念日")


@dataclass(frozen=True)
class Birthday:
    id: int
    name: str
    solar_date: dt.date
    alarm_days: tuple[int, ...] | None
    note: str
    birth_time: str
    tag: str


@dataclass(frozen=True)
class DeletedBirthday:
    id: int
    name: str
    solar_date: dt.date
    tag: str
    deleted_at: str


@dataclass(frozen=True)
class AppConfig:
    db: Path
    out: Path
    start_year: int
    end_year: int
    calendar_name: str
    alarm_days: str


def alarm_days_to_text(value: tuple[int, ...] | None) -> str:
    if value is None:
        return ""
    return ",".join(str(n) for n in value)


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD, e.g. 1990-08-15") from exc


def parse_time(value: str | None) -> str:
    if value is None:
        return ""
    raw = value.strip()
    if not raw:
        return ""
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = dt.datetime.strptime(raw, fmt).time()
            return parsed.strftime("%H:%M")
        except ValueError:
            pass
    raise ValueError("time must be HH:MM, e.g. 08:30")


def parse_tag(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "生日"
    if raw not in VALID_TAGS:
        raise ValueError(f"tag must be one of: {', '.join(VALID_TAGS)}")
    return raw


def parse_alarm_days(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    vals: list[int] = []
    for i, part in enumerate(raw.split(","), start=1):
        part = part.strip()
        if not part:
            raise ValueError(f"alarm-days item {i} is empty")
        try:
            n = int(part)
        except ValueError as exc:
            raise ValueError(f"alarm-days item {i} is not an integer: {part}") from exc
        if n < -1:
            raise ValueError("alarm-days cannot be less than -1")
        vals.append(n)
    if -1 in vals:
        return ()
    return tuple(sorted(set(vals), reverse=True))


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS birthdays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                solar_date TEXT NOT NULL,
                alarm_days TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                birth_time TEXT,
                tag TEXT NOT NULL DEFAULT '生日',
                deleted_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_birthdays_enabled
            ON birthdays(enabled, solar_date, name)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(birthdays)")}
        if "note" not in columns:
            conn.execute("ALTER TABLE birthdays ADD COLUMN note TEXT")
        if "birth_time" not in columns:
            conn.execute("ALTER TABLE birthdays ADD COLUMN birth_time TEXT")
        if "tag" not in columns:
            conn.execute("ALTER TABLE birthdays ADD COLUMN tag TEXT NOT NULL DEFAULT '生日'")
        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE birthdays ADD COLUMN deleted_at TEXT")
        conn.execute("UPDATE birthdays SET tag='生日' WHERE tag IS NULL OR TRIM(tag)='' ")


def get_setting(path: Path, key: str, default: str) -> str:
    init_db(path)
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row[0])


def set_setting(path: Path, key: str, value: str) -> None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )


def add_birthday(
    path: Path,
    name: str,
    solar_date: dt.date,
    alarm_days: tuple[int, ...] | None,
    note: str = "",
    birth_time: str = "",
    tag: str = "生日",
) -> int:
    name = name.strip()
    if not name:
        raise ValueError("name cannot be empty")
    init_db(path)
    alarm_text = None if alarm_days is None else ",".join(str(n) for n in alarm_days)
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO birthdays(name, solar_date, alarm_days, enabled, note, birth_time, tag, deleted_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, NULL)
            """,
            (name, solar_date.isoformat(), alarm_text, note.strip(), parse_time(birth_time), parse_tag(tag)),
        )
        return int(cur.lastrowid)


def update_birthday(
    path: Path,
    row_id: int,
    name: str,
    solar_date: dt.date,
    alarm_days: tuple[int, ...] | None,
    enabled: bool,
    note: str = "",
    birth_time: str = "",
    tag: str = "生日",
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("name cannot be empty")
    init_db(path)
    alarm_text = None if alarm_days is None else ",".join(str(n) for n in alarm_days)
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            """
            UPDATE birthdays
            SET name=?, solar_date=?, alarm_days=?, enabled=?, note=?, birth_time=?, tag=?, deleted_at=NULL
            WHERE id=?
            """,
            (
                name,
                solar_date.isoformat(),
                alarm_text,
                1 if enabled else 0,
                note.strip(),
                parse_time(birth_time),
                parse_tag(tag),
                row_id,
            ),
        )
        if cur.rowcount == 0:
            raise ValueError(f"birthday id not found: {row_id}")


def delete_birthday(path: Path, row_id: int) -> None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            "UPDATE birthdays SET enabled=0, deleted_at=? WHERE id=? AND enabled=1",
            (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"birthday id not found: {row_id}")


def restore_birthday(path: Path, row_id: int) -> None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        cur = conn.execute("UPDATE birthdays SET enabled=1, deleted_at=NULL WHERE id=? AND enabled=0", (row_id,))
        if cur.rowcount == 0:
            raise ValueError(f"deleted birthday id not found: {row_id}")


def restore_all_birthdays(path: Path) -> int:
    init_db(path)
    with sqlite3.connect(path) as conn:
        cur = conn.execute("UPDATE birthdays SET enabled=1, deleted_at=NULL WHERE enabled=0")
        return int(cur.rowcount)


def list_birthdays(path: Path, *, include_disabled: bool = False) -> list[Birthday]:
    if not path.exists():
        return []
    init_db(path)
    where = "" if include_disabled else "WHERE enabled=1"
    rows: list[Birthday] = []
    query = f"""
        SELECT id, name, solar_date, alarm_days, COALESCE(note,''), COALESCE(birth_time,''), COALESCE(tag,'生日')
        FROM birthdays
        {where}
        ORDER BY strftime('%m-%d', solar_date), name, id
    """
    with sqlite3.connect(path) as conn:
        for row_id, name, solar_date, alarm_days, note, birth_time, tag in conn.execute(query):
            rows.append(
                Birthday(
                    id=int(row_id),
                    name=str(name),
                    solar_date=parse_date(str(solar_date)),
                    alarm_days=parse_alarm_days(alarm_days),
                    note=str(note),
                    birth_time=str(birth_time),
                    tag=parse_tag(str(tag)),
                )
            )
    return rows


def list_deleted_birthdays(path: Path, *, limit: int = 50) -> list[DeletedBirthday]:
    if not path.exists():
        return []
    init_db(path)
    out: list[DeletedBirthday] = []
    query = """
        SELECT id, name, solar_date, COALESCE(tag,'生日'), COALESCE(deleted_at,'')
        FROM birthdays
        WHERE enabled=0
        ORDER BY deleted_at DESC, id DESC
        LIMIT ?
    """
    with sqlite3.connect(path) as conn:
        for row_id, name, solar_date, tag, deleted_at in conn.execute(query, (limit,)):
            out.append(
                DeletedBirthday(
                    id=int(row_id),
                    name=str(name),
                    solar_date=parse_date(str(solar_date)),
                    tag=parse_tag(str(tag)),
                    deleted_at=str(deleted_at),
                )
            )
    return out


def lunar_date_for(solar_date: dt.date):
    try:
        from lunardate import LunarDate
    except ImportError as exc:
        raise SystemExit("Missing dependency: lunardate. Use: pip install lunardate") from exc
    return LunarDate.fromSolarDate(solar_date.year, solar_date.month, solar_date.day)


def annual_lunar_birthday_to_solar(person: Birthday, year: int) -> dt.date:
    if year > LUNAR_MAX_YEAR:
        raise ValueError(f"current lunar conversion supports years up to {LUNAR_MAX_YEAR}")
    try:
        from lunardate import LunarDate
    except ImportError as exc:
        raise SystemExit("Missing dependency: lunardate. Use: pip install lunardate") from exc

    birth_lunar = lunar_date_for(person.solar_date)
    is_leap_month = int(getattr(birth_lunar, "isLeapMonth", False))
    try:
        return LunarDate(year, birth_lunar.month, birth_lunar.day, is_leap_month).toSolarDate()
    except ValueError:
        if is_leap_month:
            return LunarDate(year, birth_lunar.month, birth_lunar.day, 0).toSolarDate()
        raise


def chinese_day(day: int) -> str:
    names = ["", "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十", "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十", "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]
    return names[day]


def lunar_label(solar_date: dt.date) -> str:
    lunar = lunar_date_for(solar_date)
    months = ["", "正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "冬月", "腊月"]
    leap = "闰" if getattr(lunar, "isLeapMonth", False) else ""
    return f"农历{leap}{months[lunar.month]}{chinese_day(lunar.day)}"


def zodiac_for_date(solar_date: dt.date) -> str:
    lunar = lunar_date_for(solar_date)
    animals = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
    return animals[(lunar.year - 4) % 12]


def ical_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def fold_line(line: str, limit: int = 75) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= limit:
        return line
    chunks: list[bytes] = []
    rest = encoded
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = limit
        while cut > 0 and (rest[cut] & 0b1100_0000) == 0b1000_0000:
            cut -= 1
        if cut == 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:]
    return "\r\n ".join(x.decode("utf-8") for x in chunks)


def event_uid(person: Birthday, year: int) -> str:
    base = f"{person.id}|{person.name}|{person.solar_date.isoformat()}|{year}|{person.tag}"
    return f"{hashlib.sha256(base.encode('utf-8')).hexdigest()[:24]}@solar-birthday.local"


def make_event(person: Birthday, year: int, date: dt.date, alarm_days: tuple[int, ...]) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end_date = date + dt.timedelta(days=1)
    desc: list[str] = []
    if person.tag == "生日":
        age = year - person.solar_date.year
        desc.extend(
            [
                f"标签：{person.tag}",
                f"出生公历：{person.solar_date.month}月{person.solar_date.day}日",
                lunar_label(person.solar_date),
                f"生肖：{zodiac_for_date(person.solar_date)}",
                f"本年公历：{date.month}月{date.day}日",
                f"年龄：{age}岁",
            ]
        )
    else:
        nth_year = year - person.solar_date.year + 1
        desc.extend(
            [
                f"标签：{person.tag}",
                f"首年公历：{person.solar_date.month}月{person.solar_date.day}日",
                lunar_label(person.solar_date),
                f"本年公历：{date.month}月{date.day}日",
                f"第{nth_year}年",
            ]
        )
    if person.birth_time:
        desc.append(f"出生时间：{person.birth_time}")
    if person.note.strip():
        desc.append(person.note.strip())
    summary = f"{person.name}的生日" if person.tag == "生日" else person.name
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event_uid(person, year)}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}",
        f"SUMMARY:{ical_escape(summary)}",
        f"DESCRIPTION:{ical_escape(chr(10).join(desc))}",
        f"CATEGORIES:{ical_escape(person.tag)}",
        "TRANSP:TRANSPARENT",
    ]
    for alarm_day in alarm_days:
        lines.extend(
            [
                "BEGIN:VALARM",
                f"TRIGGER:-P{alarm_day}D",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{ical_escape(summary)}提醒（提前{alarm_day}天）",
                "END:VALARM",
            ]
        )
    lines.append("END:VEVENT")
    return "\r\n".join(fold_line(x) for x in lines)


def generate_ics(people: list[Birthday], out: Path, *, start_year: int, end_year: int, calendar_name: str, default_alarm_days: tuple[int, ...]) -> int:
    if end_year < start_year:
        raise ValueError("end-year must be greater than or equal to start-year")
    if end_year > LUNAR_MAX_YEAR:
        raise ValueError(f"current lunar conversion supports years up to {LUNAR_MAX_YEAR}")
    if not people:
        raise ValueError("database has no enabled birthdays")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//local/solar-birthday-cos//CN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{ical_escape(calendar_name)}", "X-WR-TIMEZONE:Asia/Shanghai", f"LAST-MODIFIED:{stamp}"]
    count = 0
    for person in people:
        first_year = max(start_year, person.solar_date.year)
        for year in range(first_year, end_year + 1):
            date = person.solar_date if year == person.solar_date.year else annual_lunar_birthday_to_solar(person, year)
            alarm_days = person.alarm_days if person.alarm_days is not None else default_alarm_days
            lines.append(make_event(person, year, date, alarm_days))
            count += 1
    lines.append("END:VCALENDAR")
    out.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return count


def birthday_to_dict(person: Birthday) -> dict[str, object]:
    return {
        "id": person.id,
        "name": person.name,
        "date": person.solar_date.isoformat(),
        "birth_time": person.birth_time,
        "tag": person.tag,
        "alarm_days": None if person.alarm_days is None else ",".join(str(n) for n in person.alarm_days),
        "note": person.note,
        "lunar": lunar_label(person.solar_date),
        "zodiac": zodiac_for_date(person.solar_date),
    }


def deleted_birthday_to_dict(person: DeletedBirthday) -> dict[str, object]:
    return {"id": person.id, "name": person.name, "date": person.solar_date.isoformat(), "tag": person.tag, "deleted_at": person.deleted_at}


class WebHandler(BaseHTTPRequestHandler):
    config: AppConfig
    static_dir: Path

    def _send_json(self, code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, object]:
        raw_len = self.headers.get("Content-Length", "0")
        length = int(raw_len)
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _serve_static(self, relative_path: str) -> None:
        target = (self.static_dir / relative_path).resolve()
        if not str(target).startswith(str(self.static_dir.resolve())):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        body = target.read_bytes()
        ctype, _ = mimetypes.guess_type(str(target))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{ctype or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _generate(self) -> int:
        default_alarm_text = get_setting(self.config.db, "default_alarm_days", self.config.alarm_days)
        return generate_ics(
            list_birthdays(self.config.db),
            self.config.out,
            start_year=self.config.start_year,
            end_year=self.config.end_year,
            calendar_name=self.config.calendar_name,
            default_alarm_days=parse_alarm_days(default_alarm_text) or (),
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/birthdays":
            init_db(self.config.db)
            default_alarm_text = get_setting(self.config.db, "default_alarm_days", self.config.alarm_days)
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "items": [birthday_to_dict(p) for p in list_birthdays(self.config.db)],
                    "config": {
                        "db": str(self.config.db),
                        "out": str(self.config.out),
                        "start_year": self.config.start_year,
                        "end_year": self.config.end_year,
                        "calendar_name": self.config.calendar_name,
                        "alarm_days": default_alarm_text,
                    },
                },
            )
            return
        if path == "/api/deleted":
            self._send_json(HTTPStatus.OK, {"ok": True, "items": [deleted_birthday_to_dict(p) for p in list_deleted_birthdays(self.config.db)]})
            return
        if path == "/birthdays.ics":
            if not self.config.out.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "birthdays.ics not generated")
                return
            body = self.config.out.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/index.html"):
            self._serve_static("index.html")
            return
        if path in ("/app.js", "/styles.css"):
            self._serve_static(path.lstrip("/"))
            return
        if path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "endpoint not found"})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/birthdays":
                body = self._read_json()
                name = str(body.get("name", "")).strip()
                date = parse_date(str(body.get("date", "")))
                note = str(body.get("note", "")).strip()
                birth_time = parse_time(None if body.get("birth_time") is None else str(body.get("birth_time")))
                tag = parse_tag(None if body.get("tag") is None else str(body.get("tag")))
                alarm_days = parse_alarm_days(None if body.get("alarm_days") is None else str(body.get("alarm_days")))
                row_id = body.get("id")
                if row_id in (None, ""):
                    new_id = add_birthday(self.config.db, name, date, alarm_days, note, birth_time, tag)
                    self._send_json(HTTPStatus.OK, {"ok": True, "id": new_id})
                else:
                    update_birthday(self.config.db, int(row_id), name, date, alarm_days, True, note, birth_time, tag)
                    self._send_json(HTTPStatus.OK, {"ok": True, "id": int(row_id)})
                return
            if path == "/api/config":
                body = self._read_json()
                default_alarm_days = parse_alarm_days(None if body.get("alarm_days") is None else str(body.get("alarm_days")))
                if default_alarm_days is None:
                    raise ValueError("default alarm-days cannot be empty")
                set_setting(self.config.db, "default_alarm_days", alarm_days_to_text(default_alarm_days))
                self._send_json(HTTPStatus.OK, {"ok": True, "alarm_days": alarm_days_to_text(default_alarm_days)})
                return
            if path == "/api/generate":
                count = self._generate()
                self._send_json(HTTPStatus.OK, {"ok": True, "message": f"Generated {count} events", "events": count})
                return
            if path == "/api/restore-all":
                count = restore_all_birthdays(self.config.db)
                self._send_json(HTTPStatus.OK, {"ok": True, "restored": count})
                return
            prefix = "/api/restore/"
            if path.startswith(prefix):
                restore_birthday(self.config.db, int(path[len(prefix):]))
                self._send_json(HTTPStatus.OK, {"ok": True})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "endpoint not found"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            prefix = "/api/birthdays/"
            if not path.startswith(prefix):
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "endpoint not found"})
                return
            delete_birthday(self.config.db, int(path[len(prefix):]))
            self._send_json(HTTPStatus.OK, {"ok": True})
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def command_init(args: argparse.Namespace) -> None:
    init_db(Path(args.db))
    print(f"Initialized: {Path(args.db).resolve()}")


def command_add(args: argparse.Namespace) -> None:
    row_id = add_birthday(Path(args.db), args.name, parse_date(args.date), parse_alarm_days(args.alarm_days), args.note, args.time, args.tag)
    print(f"Added row {row_id}: {args.name} {parse_date(args.date).isoformat()}")


def command_list(args: argparse.Namespace) -> None:
    people = list_birthdays(Path(args.db), include_disabled=args.all)
    if not people:
        print("No birthdays found")
        return
    for person in people:
        alarm = "default" if person.alarm_days is None else (",".join(str(n) for n in person.alarm_days) or "none")
        name_show = f"{person.name}的生日" if person.tag == "生日" else person.name
        print(f"{person.id}\t{name_show}\t{person.tag}\t{person.solar_date.isoformat()}\talarm_days={alarm}")


def command_generate(args: argparse.Namespace) -> None:
    start_year = args.start_year or dt.date.today().year
    count = generate_ics(list_birthdays(Path(args.db)), Path(args.out), start_year=start_year, end_year=args.end_year, calendar_name=args.calendar_name, default_alarm_days=parse_alarm_days(args.alarm_days) or ())
    print(f"Generated: {Path(args.out).resolve()}")
    print(f"Events: {count}")


def command_web(args: argparse.Namespace) -> None:
    start_year = args.start_year or dt.date.today().year
    config = AppConfig(db=Path(args.db).resolve(), out=Path(args.out).resolve(), start_year=start_year, end_year=args.end_year, calendar_name=args.calendar_name, alarm_days=args.alarm_days)
    init_db(config.db)
    static_dir = Path(__file__).resolve().parent / "web"
    if not static_dir.exists():
        raise SystemExit(f"web assets not found: {static_dir}")
    handler = type("SolarBirthdayWebHandler", (WebHandler,), {})
    handler.config = config
    handler.static_dir = static_dir
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print("Web UI started")
    print(f"Open: http://{args.host}:{args.port}/")
    print(f"DB: {config.db}")
    print(f"ICS: {config.out}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate birthday ICS from SQLite for COS upload")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create SQLite database")
    p_init.add_argument("--db", default="birthdays.db")
    p_init.set_defaults(func=command_init)

    p_add = sub.add_parser("add", help="Add a date record")
    p_add.add_argument("--db", default="birthdays.db")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--alarm-days", default=None, help="Override, e.g. 14,7,0 or -1")
    p_add.add_argument("--note", default="", help="Optional note")
    p_add.add_argument("--time", default="", help="Optional exact time, HH:MM")
    p_add.add_argument("--tag", default="生日", choices=VALID_TAGS, help="Tag")
    p_add.set_defaults(func=command_add)

    p_list = sub.add_parser("list", help="List records")
    p_list.add_argument("--db", default="birthdays.db")
    p_list.add_argument("--all", action="store_true", help="Include disabled rows")
    p_list.set_defaults(func=command_list)

    p_gen = sub.add_parser("generate", help="Generate birthdays.ics")
    p_gen.add_argument("--db", default="birthdays.db")
    p_gen.add_argument("--out", default="birthdays.ics")
    p_gen.add_argument("--start-year", type=int, default=None)
    p_gen.add_argument("--end-year", type=int, default=LUNAR_MAX_YEAR)
    p_gen.add_argument("--calendar-name", default="家庭公历生日")
    p_gen.add_argument("--alarm-days", default="7")
    p_gen.set_defaults(func=command_generate)

    p_web = sub.add_parser("web", help="Launch local visual editor")
    p_web.add_argument("--db", default="birthdays.db")
    p_web.add_argument("--out", default="birthdays.ics")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8898)
    p_web.add_argument("--start-year", type=int, default=None)
    p_web.add_argument("--end-year", type=int, default=LUNAR_MAX_YEAR)
    p_web.add_argument("--calendar-name", default="家庭公历生日")
    p_web.add_argument("--alarm-days", default="7")
    p_web.set_defaults(func=command_web)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
