"""Regras da rotina-alvo: cronograma de transição, comparação meta x real,
alertas contextuais e contador de consistência.

Premissas assumidas (documentadas para a Alana poder ajustar depois):
- O horário-alvo de "acordar de vez" é 08:00 em todos os dias (não varia
  no cronograma de transição fornecido).
- A partir do dia 11 mantém-se o mesmo alvo do dia 9-10 (fase final).
- Se a data de início da transição ainda não foi configurada, ou a data
  consultada é anterior ao início, considera-se dia 1.
"""
from datetime import datetime, date, timedelta

WAKE_TIME_TARGET = "08:00"

# dias inclusivos do cronograma de 10 dias
TRANSITION_STAGES = [
    {"day_start": 1, "day_end": 2, "nap_wake_limit": "19:30", "night_routine_start": "19:00", "sleep_target": "23:00"},
    {"day_start": 3, "day_end": 4, "nap_wake_limit": "19:00", "night_routine_start": "18:30", "sleep_target": "22:00"},
    {"day_start": 5, "day_end": 6, "nap_wake_limit": "18:30", "night_routine_start": "18:00", "sleep_target": "21:00"},
    {"day_start": 7, "day_end": 8, "nap_wake_limit": "18:00", "night_routine_start": "17:30", "sleep_target": "20:30"},
    {"day_start": 9, "day_end": 10, "nap_wake_limit": "18:00", "night_routine_start": "17:30", "sleep_target": "20:00"},
]

MARGIN_MINUTES = 15


def _hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def combine(d: date, hm: str) -> datetime:
    h, m = _hm(hm)
    return datetime(d.year, d.month, d.day, h, m)


def day_number_for(target_date: date, start_date):
    if start_date is None:
        return 1
    n = (target_date - start_date).days + 1
    return max(1, min(n, 10))


def stage_for_day(day_number: int):
    for stage in TRANSITION_STAGES:
        if stage["day_start"] <= day_number <= stage["day_end"]:
            return stage
    return TRANSITION_STAGES[-1]


def target_for_date(target_date: date, start_date):
    dn = day_number_for(target_date, start_date)
    stage = stage_for_day(dn)
    return {
        "day_number": dn,
        "wake_time": WAKE_TIME_TARGET,
        "nap_wake_limit": stage["nap_wake_limit"],
        "night_routine_start": stage["night_routine_start"],
        "sleep_target": stage["sleep_target"],
    }


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def fetch_window_events(conn, target_date: date):
    """Eventos relevantes: do meio-dia do dia anterior ao meio-dia do dia seguinte,
    mais qualquer soneca ainda aberta (end_ts nulo) começada antes disso."""
    lo = datetime.combine(target_date - timedelta(days=1), datetime.min.time()).replace(hour=12)
    hi = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).replace(hour=12)
    rows = conn.execute(
        "SELECT * FROM events WHERE start_ts >= ? AND start_ts < ? ORDER BY start_ts",
        (lo.isoformat(), hi.isoformat()),
    ).fetchall()
    open_sleep = conn.execute(
        "SELECT * FROM events WHERE type='sleep' AND end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
    ).fetchone()
    events = [dict(r) for r in rows]
    if open_sleep and not any(e["id"] == open_sleep["id"] for e in events):
        events.append(dict(open_sleep))
        events.sort(key=lambda e: e["start_ts"])
    return events


def classify_checkpoints(events, target_date: date):
    """Retorna dict com horários reais observados para os 4 marcos do dia."""
    day_start = datetime.combine(target_date, datetime.min.time())

    def in_range(dt, h1, h2):
        lo = day_start.replace(hour=h1)
        hi = day_start.replace(hour=0) + timedelta(hours=h2)
        return lo <= dt < hi

    sleeps = [e for e in events if e["type"] == "sleep"]

    morning_wake = None
    for e in sleeps:
        end = _parse(e["end_ts"])
        if end and in_range(end, 5, 11):
            if morning_wake is None or end > morning_wake:
                morning_wake = end

    nap_end = None
    for e in sleeps:
        end = _parse(e["end_ts"])
        if end and in_range(end, 12, 21):
            if nap_end is None or end > nap_end:
                nap_end = end

    night_routine_start = None
    baths_today = [e for e in events if e["type"] == "bath" and in_range(_parse(e["start_ts"]), 15, 24)]
    if baths_today:
        night_routine_start = min(_parse(e["start_ts"]) for e in baths_today)
    else:
        feeds_evening = [e for e in events if e["type"] == "feed" and in_range(_parse(e["start_ts"]), 16, 24)]
        if feeds_evening:
            night_routine_start = min(_parse(e["start_ts"]) for e in feeds_evening)

    sleep_start = None
    for e in sleeps:
        start = _parse(e["start_ts"])
        if start and day_start.replace(hour=18) <= start < day_start.replace(hour=23, minute=59, second=59):
            if sleep_start is None or start < sleep_start:
                sleep_start = start

    open_sleep = next((e for e in sleeps if e["end_ts"] is None), None)

    return {
        "wake": morning_wake,
        "nap_end": nap_end,
        "night_routine_start": night_routine_start,
        "sleep_start": sleep_start,
        "open_sleep": open_sleep,
    }


CHECKPOINT_LABELS = {
    "wake": "Acordar de vez",
    "nap_end": "Fim da soneca da tarde",
    "night_routine_start": "Início da rotina noturna",
    "sleep_start": "Dormir",
}


def build_comparison(target_date: date, target, checkpoints):
    target_map = {
        "wake": target["wake_time"],
        "nap_end": target["nap_wake_limit"],
        "night_routine_start": target["night_routine_start"],
        "sleep_start": target["sleep_target"],
    }
    result = []
    for key in ("wake", "nap_end", "night_routine_start", "sleep_start"):
        target_dt = combine(target_date, target_map[key])
        actual_dt = checkpoints.get(key)
        item = {
            "key": key,
            "label": CHECKPOINT_LABELS[key],
            "target": target_map[key],
            "actual": actual_dt.strftime("%H:%M") if actual_dt else None,
        }
        if actual_dt is None:
            item["delta_min"] = None
            item["status"] = "pending"
        else:
            delta = round((actual_dt - target_dt).total_seconds() / 60)
            item["delta_min"] = delta
            if abs(delta) <= MARGIN_MINUTES:
                item["status"] = "on_target"
            elif delta > 0:
                item["status"] = "late"
            else:
                item["status"] = "early"
        result.append(item)
    return result


def day_met_target(comparison):
    if any(c["status"] == "pending" for c in comparison):
        return False
    return all(c["status"] == "on_target" for c in comparison)


def build_alerts(now: datetime, target, checkpoints):
    alerts = []
    open_sleep = checkpoints.get("open_sleep")
    today = now.date()

    if open_sleep:
        start = _parse(open_sleep["start_ts"])
        if start.hour >= 11 and start.hour < 18:
            limit_dt = combine(today, target["nap_wake_limit"])
            if now > limit_dt:
                late_min = round((now - limit_dt).total_seconds() / 60)
                new_routine = combine(today, target["night_routine_start"]) + timedelta(minutes=late_min)
                new_sleep = combine(today, target["sleep_target"]) + timedelta(minutes=late_min)
                alerts.append({
                    "type": "nap_overrun",
                    "severity": "warning",
                    "message": (
                        f"A soneca da tarde já passou {late_min} min do limite "
                        f"({target['nap_wake_limit']}) e ainda está em andamento. "
                        f"Ajuste sugerido para hoje: iniciar a rotina noturna às "
                        f"{new_routine.strftime('%H:%M')} e mirar dormir por volta das "
                        f"{new_sleep.strftime('%H:%M')}."
                    ),
                })

    nap_end = checkpoints.get("nap_end")
    if nap_end:
        limit_dt = combine(today, target["nap_wake_limit"])
        delta = round((nap_end - limit_dt).total_seconds() / 60)
        if delta > MARGIN_MINUTES:
            new_routine = combine(today, target["night_routine_start"]) + timedelta(minutes=delta)
            new_sleep = combine(today, target["sleep_target"]) + timedelta(minutes=delta)
            alerts.append({
                "type": "nap_overrun_closed",
                "severity": "warning",
                "message": (
                    f"A soneca da tarde terminou {delta} min depois do previsto "
                    f"({target['nap_wake_limit']}). Ajuste sugerido: rotina noturna às "
                    f"{new_routine.strftime('%H:%M')}, dormir por volta das "
                    f"{new_sleep.strftime('%H:%M')}."
                ),
            })

    return alerts


def early_wake_alerts(events, target_date: date):
    """Sonecas/sono que terminaram antes das 6h — alerta para manter escuro."""
    alerts = []
    day_start = datetime.combine(target_date, datetime.min.time())
    for e in events:
        if e["type"] != "sleep" or not e["end_ts"]:
            continue
        end = _parse(e["end_ts"])
        if day_start <= end < day_start.replace(hour=6):
            alerts.append({
                "type": "early_wake",
                "severity": "info",
                "message": (
                    f"O bebê acordou às {end.strftime('%H:%M')}, antes das 6h. "
                    f"Mantenha o ambiente escuro e evite estímulos até as 8h — "
                    f"não antecipe o 'acordar de vez'."
                ),
            })
    return alerts


def work_collisions(work_events, events):
    """Marca compromissos de trabalho que colidem com sonecas reais (em andamento ou concluídas)."""
    sleeps = [e for e in events if e["type"] == "sleep"]
    result = []
    for w in work_events:
        w_start = _parse(w["start_ts"])
        w_end = _parse(w["end_ts"])
        collision = False
        for s in sleeps:
            s_start = _parse(s["start_ts"])
            s_end = _parse(s["end_ts"]) or datetime.now()
            if s_start < w_end and w_start < s_end:
                collision = True
                break
        item = dict(w)
        item["collision"] = collision
        result.append(item)
    return result
