#!/usr/bin/env python3
"""Rastreador de rotina da família (bebê, Rapha, casa e rotina pessoal).

Servidor local, sem dependencias externas (so biblioteca padrao do
Python 3, que ja vem instalada no macOS). Roda no Mac; o iPhone acessa
pelo Safari usando o IP do Mac na mesma rede Wi-Fi.

Uso:
    python3 server.py
"""
import json
import socket
import os
import sys
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db
import routine

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = 8420

VALID_EVENT_TYPES = {"feed", "bath", "sleep_start", "sleep_end"}
VALID_SUBTYPES = {"peito", "mamadeira"}
VALID_PERSONS = {"bebe", "rapha"}
VALID_FLAG_KEYS = {routine.CHILDREN_BEDTIME_KEY, routine.MOM_SELF_CARE_KEY}
HOUSE_TASK_KEYS = {t["key"] for t in routine.HOUSE_TASKS}

PERSON_CONFIG = {
    "bebe": {
        "label": "Bebê",
        "checkpoints": routine.BEBE_CHECKPOINTS,
        "delay_fields": [("night_routine_start", "iniciar a rotina noturna"), ("sleep_target", "dormir")],
    },
    "rapha": {
        "label": "Rapha",
        "checkpoints": routine.RAPHA_CHECKPOINTS,
        "delay_fields": [("sleep_target", "dormir")],
    },
}


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_start_date(conn):
    raw = get_setting(conn, "transition_start_date")
    if not raw:
        return None
    return date.fromisoformat(raw)


def person_target(conn, target_date: date, person: str):
    if person == "bebe":
        return routine.target_for_date(target_date, get_start_date(conn))
    return routine.target_for_rapha()


def build_person_state(conn, target_date: date, person: str):
    cfg = PERSON_CONFIG[person]
    target = person_target(conn, target_date, person)
    events = routine.fetch_window_events(conn, target_date, person)
    checkpoints = routine.classify_checkpoints(events, target_date)
    comparison = routine.build_comparison(target_date, target, checkpoints, cfg["checkpoints"])

    now = datetime.now()
    alerts = []
    if target_date == now.date():
        alerts += routine.build_alerts(now, target, checkpoints, cfg["delay_fields"])
    alerts += routine.early_wake_alerts(events, target_date, cfg["label"])

    day_events = [e for e in events if e["start_ts"][:10] == target_date.isoformat()
                  or (e["end_ts"] and e["end_ts"][:10] == target_date.isoformat())]
    day_events.sort(key=lambda e: e["start_ts"])

    state = {
        "person": person,
        "label": cfg["label"],
        "date": target_date.isoformat(),
        "day_number": target.get("day_number"),
        "target": target,
        "events": day_events,
        "comparison": comparison,
        "day_met_target": routine.day_met_target(comparison),
        "alerts": alerts,
    }

    if person == "bebe":
        state["start_date_configured"] = get_start_date(conn) is not None
        work_rows = conn.execute(
            "SELECT * FROM work_events WHERE date=? ORDER BY start_ts", (target_date.isoformat(),)
        ).fetchall()
        state["work_events"] = routine.work_collisions([dict(r) for r in work_rows], events)

    return state


def day_combined_status(conn, target_date: date):
    bebe = build_person_state(conn, target_date, "bebe")
    rapha = build_person_state(conn, target_date, "rapha")
    checks = routine.get_daily_checks(conn, target_date)
    house = routine.house_progress(checks)
    bedtime = routine.bedtime_status(checks, datetime.now(), target_date)
    self_care = routine.self_care_status(checks)

    met = routine.day_fully_met(
        bebe["day_met_target"], rapha["day_met_target"], house["complete"], bedtime["on_time"], self_care["done"]
    )
    failed = []
    if not bebe["day_met_target"]:
        failed.append("Bebê")
    if not rapha["day_met_target"]:
        failed.append("Rapha")
    if not house["complete"]:
        failed.append("Casa")
    if not bedtime["on_time"]:
        failed.append("Crianças na cama")
    if not self_care["done"]:
        failed.append("Rotina pessoal")

    has_data = (
        any(c["status"] != "pending" for c in bebe["comparison"] + rapha["comparison"])
        or house["done_minutes"] > 0
        or bedtime["done"]
        or self_care["done"]
    )

    return {
        "met": met,
        "has_data": has_data,
        "failed": failed,
        "bebe": bebe,
        "rapha": rapha,
        "house": house,
        "bedtime": bedtime,
        "self_care": self_care,
    }


def compute_streak(conn, upto: date):
    streak = 0
    d = upto - timedelta(days=1)  # dias completos, sem contar hoje
    for _ in range(365):
        status = day_combined_status(conn, d)
        if status["met"]:
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return streak


def build_week_summary(conn, upto: date):
    days = []
    for i in range(6, -1, -1):
        d = upto - timedelta(days=i)
        status = day_combined_status(conn, d)
        days.append({
            "date": d.isoformat(),
            "met": status["met"],
            "has_data": status["has_data"],
            "failed_checkpoints": status["failed"],
        })
    return days


class Handler(BaseHTTPRequestHandler):
    server_version = "RotinaFamilia/2.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        fpath = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not fpath.startswith(STATIC_DIR) or not os.path.isfile(fpath):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(fpath)[1]
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(ext, "application/octet-stream")
        with open(fpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_date_param(self, qs, key="date"):
        raw = qs.get(key, [None])[0]
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
        return date.today()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        conn = db.get_conn()

        if parsed.path == "/api/state":
            d = self._parse_date_param(qs)
            if d is None:
                return self._send_error_json("data invalida")
            person = qs.get("person", ["bebe"])[0]
            if person not in VALID_PERSONS:
                return self._send_error_json("pessoa invalida")
            return self._send_json(build_person_state(conn, d, person))

        if parsed.path == "/api/house":
            d = self._parse_date_param(qs)
            checks = routine.get_daily_checks(conn, d)
            progress = routine.house_progress(checks)
            progress["date"] = d.isoformat()
            return self._send_json(progress)

        if parsed.path == "/api/flags":
            d = self._parse_date_param(qs)
            checks = routine.get_daily_checks(conn, d)
            return self._send_json({
                "date": d.isoformat(),
                "bedtime": routine.bedtime_status(checks, datetime.now(), d),
                "self_care": routine.self_care_status(checks),
            })

        if parsed.path == "/api/overview":
            d = self._parse_date_param(qs)
            status = day_combined_status(conn, d)
            return self._send_json({
                "date": d.isoformat(),
                "bebe": {
                    "met": status["bebe"]["day_met_target"],
                    "day_number": status["bebe"]["day_number"],
                    "alerts": status["bebe"]["alerts"],
                },
                "rapha": {
                    "met": status["rapha"]["day_met_target"],
                    "alerts": status["rapha"]["alerts"],
                },
                "house": status["house"],
                "bedtime": status["bedtime"],
                "self_care": status["self_care"],
                "day_all_met": status["met"],
                "streak": compute_streak(conn, d),
            })

        if parsed.path == "/api/week":
            d = self._parse_date_param(qs)
            return self._send_json({
                "days": build_week_summary(conn, d),
                "streak": compute_streak(conn, d),
            })

        if parsed.path == "/api/settings":
            return self._send_json({
                "transition_start_date": get_setting(conn, "transition_start_date"),
            })

        if parsed.path == "/api/work_events":
            d = self._parse_date_param(qs)
            rows = conn.execute(
                "SELECT * FROM work_events WHERE date=? ORDER BY start_ts", (d.isoformat(),)
            ).fetchall()
            return self._send_json({"work_events": [dict(r) for r in rows]})

        return self._serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        conn = db.get_conn()
        body = self._read_json_body()
        if body is None:
            return self._send_error_json("JSON invalido")

        if parsed.path == "/api/events":
            return self._handle_create_event(conn, body)

        if parsed.path == "/api/work_events":
            return self._handle_create_work_event(conn, body)

        if parsed.path == "/api/house/toggle":
            return self._handle_house_toggle(conn, body)

        if parsed.path == "/api/flags":
            return self._handle_set_flag(conn, body)

        if parsed.path == "/api/settings":
            raw = body.get("transition_start_date")
            if raw:
                try:
                    date.fromisoformat(raw)
                except ValueError:
                    return self._send_error_json("data invalida")
            set_setting(conn, "transition_start_date", raw)
            return self._send_json({"ok": True})

        self.send_response(404)
        self.end_headers()

    def _handle_create_event(self, conn, body):
        etype = body.get("type")
        if etype not in VALID_EVENT_TYPES:
            return self._send_error_json("tipo de evento invalido")
        person = body.get("person", "bebe")
        if person not in VALID_PERSONS:
            return self._send_error_json("pessoa invalida")
        if etype == "feed" and person != "bebe":
            return self._send_error_json("mamada se aplica somente ao bebê")
        now = datetime.now().isoformat(timespec="seconds")

        if etype == "feed":
            subtype = body.get("subtype")
            if subtype not in VALID_SUBTYPES:
                return self._send_error_json("subtipo invalido (peito ou mamadeira)")
            cur = conn.execute(
                "INSERT INTO events(person, type, subtype, start_ts, end_ts, created_at) VALUES (?,?,?,?,?,?)",
                (person, "feed", subtype, now, now, now),
            )
        elif etype == "bath":
            cur = conn.execute(
                "INSERT INTO events(person, type, subtype, start_ts, end_ts, created_at) VALUES (?,?,?,?,?,?)",
                (person, "bath", None, now, now, now),
            )
        elif etype == "sleep_start":
            open_sleep = conn.execute(
                "SELECT id FROM events WHERE person=? AND type='sleep' AND end_ts IS NULL", (person,)
            ).fetchone()
            if open_sleep:
                return self._send_error_json("ja existe uma soneca em andamento")
            cur = conn.execute(
                "INSERT INTO events(person, type, subtype, start_ts, end_ts, created_at) VALUES (?,?,?,?,?,?)",
                (person, "sleep", None, now, None, now),
            )
        elif etype == "sleep_end":
            open_sleep = conn.execute(
                "SELECT id FROM events WHERE person=? AND type='sleep' AND end_ts IS NULL "
                "ORDER BY start_ts DESC LIMIT 1",
                (person,),
            ).fetchone()
            if not open_sleep:
                return self._send_error_json("nao ha soneca em andamento")
            conn.execute("UPDATE events SET end_ts=? WHERE id=?", (now, open_sleep["id"]))
            conn.commit()
            return self._send_json({"ok": True, "id": open_sleep["id"]})

        conn.commit()
        return self._send_json({"ok": True, "id": cur.lastrowid})

    def _handle_create_work_event(self, conn, body):
        d = body.get("date")
        title = (body.get("title") or "Compromisso").strip()
        start_hm = body.get("start")
        end_hm = body.get("end")
        if not d or not start_hm or not end_hm:
            return self._send_error_json("date, start e end sao obrigatorios")
        try:
            target_date = date.fromisoformat(d)
            start_ts = routine.combine(target_date, start_hm).isoformat(timespec="seconds")
            end_ts = routine.combine(target_date, end_hm).isoformat(timespec="seconds")
        except ValueError:
            return self._send_error_json("formato de data/hora invalido")
        cur = conn.execute(
            "INSERT INTO work_events(date, title, start_ts, end_ts) VALUES (?,?,?,?)",
            (d, title, start_ts, end_ts),
        )
        conn.commit()
        return self._send_json({"ok": True, "id": cur.lastrowid})

    def _handle_house_toggle(self, conn, body):
        d = body.get("date")
        key = body.get("key")
        done = bool(body.get("done"))
        if key not in HOUSE_TASK_KEYS:
            return self._send_error_json("tarefa invalida")
        try:
            target_date = date.fromisoformat(d) if d else date.today()
        except ValueError:
            return self._send_error_json("data invalida")
        routine.set_daily_check(conn, target_date, f"house:{key}", done)
        checks = routine.get_daily_checks(conn, target_date)
        return self._send_json(routine.house_progress(checks))

    def _handle_set_flag(self, conn, body):
        d = body.get("date")
        key = body.get("key")
        done = bool(body.get("done"))
        if key not in VALID_FLAG_KEYS:
            return self._send_error_json("flag invalida")
        try:
            target_date = date.fromisoformat(d) if d else date.today()
        except ValueError:
            return self._send_error_json("data invalida")
        routine.set_daily_check(conn, target_date, key, done)
        checks = routine.get_daily_checks(conn, target_date)
        return self._send_json({
            "bedtime": routine.bedtime_status(checks, datetime.now(), target_date),
            "self_care": routine.self_care_status(checks),
        })

    def do_DELETE(self):
        parsed = urlparse(self.path)
        conn = db.get_conn()
        parts = parsed.path.strip("/").split("/")

        if len(parts) == 3 and parts[0] == "api" and parts[1] == "events":
            try:
                event_id = int(parts[2])
            except ValueError:
                return self._send_error_json("id invalido")
            conn.execute("DELETE FROM events WHERE id=?", (event_id,))
            conn.commit()
            return self._send_json({"ok": True})

        if len(parts) == 3 and parts[0] == "api" and parts[1] == "work_events":
            try:
                event_id = int(parts[2])
            except ValueError:
                return self._send_error_json("id invalido")
            conn.execute("DELETE FROM work_events WHERE id=?", (event_id,))
            conn.commit()
            return self._send_json({"ok": True})

        self.send_response(404)
        self.end_headers()


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def main():
    db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    ip = local_ip()
    print("=" * 56)
    print(" Rastreador de rotina da família")
    print("=" * 56)
    print(f" Neste Mac:        http://localhost:{PORT}")
    print(f" No iPhone (mesma rede Wi-Fi): http://{ip}:{PORT}")
    print("=" * 56)
    print(" Ctrl+C para parar")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando...")
        server.shutdown()


if __name__ == "__main__":
    main()
