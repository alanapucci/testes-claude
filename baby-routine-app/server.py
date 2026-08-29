#!/usr/bin/env python3
"""Rastreador de rotina do bebe.

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


def build_day_state(conn, target_date: date):
    start_date = get_start_date(conn)
    target = routine.target_for_date(target_date, start_date)
    events = routine.fetch_window_events(conn, target_date)
    checkpoints = routine.classify_checkpoints(events, target_date)
    comparison = routine.build_comparison(target_date, target, checkpoints)

    now = datetime.now()
    alerts = []
    if target_date == now.date():
        alerts += routine.build_alerts(now, target, checkpoints)
    alerts += routine.early_wake_alerts(events, target_date)

    day_events = [e for e in events if e["start_ts"][:10] == target_date.isoformat()
                  or (e["end_ts"] and e["end_ts"][:10] == target_date.isoformat())]
    day_events.sort(key=lambda e: e["start_ts"])

    work_rows = conn.execute(
        "SELECT * FROM work_events WHERE date=? ORDER BY start_ts", (target_date.isoformat(),)
    ).fetchall()
    work_events = routine.work_collisions([dict(r) for r in work_rows], events)

    return {
        "date": target_date.isoformat(),
        "day_number": target["day_number"],
        "start_date_configured": start_date is not None,
        "target": target,
        "events": day_events,
        "comparison": comparison,
        "day_met_target": routine.day_met_target(comparison),
        "alerts": alerts,
        "work_events": work_events,
    }


def compute_streak(conn, upto: date):
    start_date = get_start_date(conn)
    streak = 0
    d = upto - timedelta(days=1)  # dias completos, sem contar hoje
    for _ in range(365):
        target = routine.target_for_date(d, start_date)
        events = routine.fetch_window_events(conn, d)
        checkpoints = routine.classify_checkpoints(events, d)
        comparison = routine.build_comparison(d, target, checkpoints)
        if routine.day_met_target(comparison):
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return streak


def build_week_summary(conn, upto: date):
    start_date = get_start_date(conn)
    days = []
    for i in range(6, -1, -1):
        d = upto - timedelta(days=i)
        target = routine.target_for_date(d, start_date)
        events = routine.fetch_window_events(conn, d)
        checkpoints = routine.classify_checkpoints(events, d)
        comparison = routine.build_comparison(d, target, checkpoints)
        failed = [c["label"] for c in comparison if c["status"] not in ("on_target",)]
        days.append({
            "date": d.isoformat(),
            "met": routine.day_met_target(comparison),
            "has_data": any(c["status"] != "pending" for c in comparison),
            "failed_checkpoints": failed,
        })
    return days


class Handler(BaseHTTPRequestHandler):
    server_version = "RotinaBebe/1.0"

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
            return self._send_json(build_day_state(conn, d))

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
        now = datetime.now().isoformat(timespec="seconds")

        if etype == "feed":
            subtype = body.get("subtype")
            if subtype not in VALID_SUBTYPES:
                return self._send_error_json("subtipo invalido (peito ou mamadeira)")
            cur = conn.execute(
                "INSERT INTO events(type, subtype, start_ts, end_ts, created_at) VALUES (?,?,?,?,?)",
                ("feed", subtype, now, now, now),
            )
        elif etype == "bath":
            cur = conn.execute(
                "INSERT INTO events(type, subtype, start_ts, end_ts, created_at) VALUES (?,?,?,?,?)",
                ("bath", None, now, now, now),
            )
        elif etype == "sleep_start":
            open_sleep = conn.execute(
                "SELECT id FROM events WHERE type='sleep' AND end_ts IS NULL"
            ).fetchone()
            if open_sleep:
                return self._send_error_json("ja existe uma soneca em andamento")
            cur = conn.execute(
                "INSERT INTO events(type, subtype, start_ts, end_ts, created_at) VALUES (?,?,?,?,?)",
                ("sleep", None, now, None, now),
            )
        elif etype == "sleep_end":
            open_sleep = conn.execute(
                "SELECT id FROM events WHERE type='sleep' AND end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
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
    print(" Rastreador de rotina do bebe")
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
