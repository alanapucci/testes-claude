"""Regras da rotina-alvo: cronograma de transição do bebê, rotina fixa do
Rapha, checklist da casa, flags diárias (crianças na cama / rotina pessoal
da mãe), comparação meta x real, alertas contextuais e contador de
consistência combinado.

Premissas assumidas (documentadas para a Alana poder ajustar depois):
- O horário-alvo de "acordar de vez" do bebê é 08:00 em todos os dias
  (não varia no cronograma de transição fornecido).
- A partir do dia 11 do cronograma do bebê mantém-se o mesmo alvo do
  dia 9-10 (fase final).
- Se a data de início da transição do bebê ainda não foi configurada,
  ou a data consultada é anterior ao início, considera-se dia 1.
- O Rapha não está em transição: usa um alvo fixo diário (fim da soneca
  da tarde ~18:00, banho ~18:00, dormir ~20:30), tirado da rotina-alvo
  do dia inteiro da família.
- "Todas as crianças na cama" tem prazo fixo às 21:00, sem margem — é
  tratado como sim/não feito até esse horário.
"""
from datetime import datetime, date, timedelta

MARGIN_MINUTES = 15

# ---------------------------------------------------------------------------
# Bebê: cronograma de transição de 10 dias
# ---------------------------------------------------------------------------

WAKE_TIME_TARGET = "08:00"

TRANSITION_STAGES = [
    {"day_start": 1, "day_end": 2, "nap_wake_limit": "19:30", "night_routine_start": "19:00", "sleep_target": "23:00"},
    {"day_start": 3, "day_end": 4, "nap_wake_limit": "19:00", "night_routine_start": "18:30", "sleep_target": "22:00"},
    {"day_start": 5, "day_end": 6, "nap_wake_limit": "18:30", "night_routine_start": "18:00", "sleep_target": "21:00"},
    {"day_start": 7, "day_end": 8, "nap_wake_limit": "18:00", "night_routine_start": "17:30", "sleep_target": "20:30"},
    {"day_start": 9, "day_end": 10, "nap_wake_limit": "18:00", "night_routine_start": "17:30", "sleep_target": "20:00"},
]

BEBE_CHECKPOINTS = [
    ("wake", "Acordar de vez", "wake_time"),
    ("nap_end", "Fim da soneca da tarde", "nap_wake_limit"),
    ("night_routine_start", "Início da rotina noturna", "night_routine_start"),
    ("sleep_start", "Dormir", "sleep_target"),
]

# ---------------------------------------------------------------------------
# Rapha (3 anos): alvo fixo, sem transição, sem mamada
# ---------------------------------------------------------------------------

RAPHA_TARGET = {
    "nap_wake_limit": "18:00",   # fim da soneca da tarde
    "bath_time": "18:00",       # banho (junto ou em sequência com o bebê)
    "sleep_target": "20:30",    # dorme por volta das 20h30
}

RAPHA_CHECKPOINTS = [
    ("nap_end", "Fim da soneca da tarde", "nap_wake_limit"),
    ("bath", "Banho", "bath_time"),
    ("sleep_start", "Dormir", "sleep_target"),
]

# ---------------------------------------------------------------------------
# Casa: checklist diário
# ---------------------------------------------------------------------------

HOUSE_TASKS = [
    {"key": "basico", "label": "Básico (camas, louça, organização)", "minutes": 40},
    {"key": "cozinha", "label": "Cozinha", "minutes": 15},
    {"key": "quarto1", "label": "Quarto 1", "minutes": 15},
    {"key": "quarto2", "label": "Quarto 2", "minutes": 15},
    {"key": "quarto3", "label": "Quarto 3", "minutes": 15},
    {"key": "banheiro1", "label": "Banheiro 1", "minutes": 15},
    {"key": "banheiro2", "label": "Banheiro 2", "minutes": 15},
    {"key": "varanda", "label": "Varanda", "minutes": 15},
    {"key": "sala", "label": "Sala", "minutes": 15},
]
HOUSE_TOTAL_MINUTES = sum(t["minutes"] for t in HOUSE_TASKS)

# ---------------------------------------------------------------------------
# Flags diárias simples (sim/não)
# ---------------------------------------------------------------------------

CHILDREN_BEDTIME_KEY = "children_bedtime"
CHILDREN_BEDTIME_LABEL = "Todas as crianças na cama"
CHILDREN_BEDTIME_DEADLINE = "21:00"

MOM_SELF_CARE_KEY = "mom_self_care"
MOM_SELF_CARE_LABEL = "Rotina de cuidados pessoais"


def _hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def combine(d: date, hm: str) -> datetime:
    h, m = _hm(hm)
    return datetime(d.year, d.month, d.day, h, m)


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


# ---------------------------------------------------------------------------
# Alvo do bebê (cronograma de transição)
# ---------------------------------------------------------------------------

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


def target_for_rapha():
    return dict(RAPHA_TARGET)


# ---------------------------------------------------------------------------
# Eventos (sono / banho / mamada) por pessoa
# ---------------------------------------------------------------------------

def fetch_window_events(conn, target_date: date, person: str):
    """Eventos de uma pessoa: do meio-dia do dia anterior ao meio-dia do dia
    seguinte, mais qualquer soneca ainda aberta (end_ts nulo) começada antes
    disso."""
    lo = datetime.combine(target_date - timedelta(days=1), datetime.min.time()).replace(hour=12)
    hi = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).replace(hour=12)
    rows = conn.execute(
        "SELECT * FROM events WHERE person=? AND start_ts >= ? AND start_ts < ? ORDER BY start_ts",
        (person, lo.isoformat(), hi.isoformat()),
    ).fetchall()
    open_sleep = conn.execute(
        "SELECT * FROM events WHERE person=? AND type='sleep' AND end_ts IS NULL "
        "ORDER BY start_ts DESC LIMIT 1",
        (person,),
    ).fetchone()
    events = [dict(r) for r in rows]
    if open_sleep and not any(e["id"] == open_sleep["id"] for e in events):
        events.append(dict(open_sleep))
        events.sort(key=lambda e: e["start_ts"])
    return events


def classify_checkpoints(events, target_date: date):
    """Retorna dict com horários reais observados para os marcos do dia de
    uma pessoa. `events` já deve estar filtrado para essa pessoa."""
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

    bath_time = None
    baths_today = [e for e in events if e["type"] == "bath" and in_range(_parse(e["start_ts"]), 15, 24)]
    if baths_today:
        bath_time = min(_parse(e["start_ts"]) for e in baths_today)

    night_routine_start = bath_time
    if night_routine_start is None:
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
        "bath": bath_time,
        "night_routine_start": night_routine_start,
        "sleep_start": sleep_start,
        "open_sleep": open_sleep,
    }


def build_comparison(target_date: date, target, checkpoints, spec):
    """spec: lista de (chave_checkpoint, rótulo, chave_no_dict_target)."""
    result = []
    for key, label, target_key in spec:
        target_hm = target[target_key]
        target_dt = combine(target_date, target_hm)
        actual_dt = checkpoints.get(key)
        item = {
            "key": key,
            "label": label,
            "target": target_hm,
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
    if not comparison or any(c["status"] == "pending" for c in comparison):
        return False
    return all(c["status"] == "on_target" for c in comparison)


def build_alerts(now: datetime, target, checkpoints, delay_fields):
    """Alertas de soneca da tarde atrasada, com sugestão de ajuste no resto
    do dia. `delay_fields`: lista de (chave_no_target, rótulo) a deslocar."""
    alerts = []
    open_sleep = checkpoints.get("open_sleep")
    today = now.date()
    nap_limit_hm = target["nap_wake_limit"]

    def suggestion(late_min):
        parts = []
        for key, label in delay_fields:
            new_dt = combine(today, target[key]) + timedelta(minutes=late_min)
            parts.append(f"{label} às {new_dt.strftime('%H:%M')}")
        return ", ".join(parts)

    if open_sleep:
        start = _parse(open_sleep["start_ts"])
        if 11 <= start.hour < 18:
            limit_dt = combine(today, nap_limit_hm)
            if now > limit_dt:
                late_min = round((now - limit_dt).total_seconds() / 60)
                alerts.append({
                    "type": "nap_overrun",
                    "severity": "warning",
                    "message": (
                        f"A soneca da tarde já passou {late_min} min do limite "
                        f"({nap_limit_hm}) e ainda está em andamento. "
                        f"Ajuste sugerido para hoje: {suggestion(late_min)}."
                    ),
                })

    nap_end = checkpoints.get("nap_end")
    if nap_end:
        limit_dt = combine(today, nap_limit_hm)
        delta = round((nap_end - limit_dt).total_seconds() / 60)
        if delta > MARGIN_MINUTES:
            alerts.append({
                "type": "nap_overrun_closed",
                "severity": "warning",
                "message": (
                    f"A soneca da tarde terminou {delta} min depois do previsto "
                    f"({nap_limit_hm}). Ajuste sugerido: {suggestion(delta)}."
                ),
            })

    return alerts


def early_wake_alerts(events, target_date: date, person_label: str):
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
                    f"{person_label} acordou às {end.strftime('%H:%M')}, antes das 6h. "
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


# ---------------------------------------------------------------------------
# Casa e flags diárias
# ---------------------------------------------------------------------------

def house_task_keys():
    return {f"house:{t['key']}" for t in HOUSE_TASKS}


def get_daily_checks(conn, target_date: date):
    """Todas as marcações do dia (casa + flags), indexadas por key."""
    rows = conn.execute(
        "SELECT key, done_at FROM daily_checks WHERE date=?", (target_date.isoformat(),)
    ).fetchall()
    return {r["key"]: r["done_at"] for r in rows}


def set_daily_check(conn, target_date: date, key: str, done: bool):
    if done:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO daily_checks(date, key, done_at) VALUES (?,?,?) "
            "ON CONFLICT(date, key) DO UPDATE SET done_at=excluded.done_at",
            (target_date.isoformat(), key, now),
        )
    else:
        conn.execute(
            "DELETE FROM daily_checks WHERE date=? AND key=?", (target_date.isoformat(), key)
        )
    conn.commit()


def house_progress(checks: dict):
    tasks = []
    done_minutes = 0
    for t in HOUSE_TASKS:
        key = f"house:{t['key']}"
        done_at = checks.get(key)
        if done_at:
            done_minutes += t["minutes"]
        tasks.append({
            "key": t["key"],
            "label": t["label"],
            "minutes": t["minutes"],
            "done": bool(done_at),
            "done_at": done_at,
        })
    percent = round(100 * done_minutes / HOUSE_TOTAL_MINUTES) if HOUSE_TOTAL_MINUTES else 0
    return {
        "tasks": tasks,
        "done_minutes": done_minutes,
        "total_minutes": HOUSE_TOTAL_MINUTES,
        "percent": percent,
        "complete": done_minutes >= HOUSE_TOTAL_MINUTES,
    }


def bedtime_status(checks: dict, now: datetime, target_date: date):
    done_at = checks.get(CHILDREN_BEDTIME_KEY)
    deadline_dt = combine(target_date, CHILDREN_BEDTIME_DEADLINE)
    on_time = False
    if done_at:
        on_time = _parse(done_at) <= deadline_dt
    late_alert = (
        not done_at
        and target_date == now.date()
        and now > deadline_dt
    )
    return {
        "key": CHILDREN_BEDTIME_KEY,
        "label": CHILDREN_BEDTIME_LABEL,
        "deadline": CHILDREN_BEDTIME_DEADLINE,
        "done": bool(done_at),
        "done_at": done_at,
        "on_time": on_time,
        "alert": late_alert,
    }


def self_care_status(checks: dict):
    done_at = checks.get(MOM_SELF_CARE_KEY)
    return {
        "key": MOM_SELF_CARE_KEY,
        "label": MOM_SELF_CARE_LABEL,
        "done": bool(done_at),
        "done_at": done_at,
    }


def day_fully_met(bebe_met, rapha_met, house_complete, bedtime_on_time, self_care_done):
    return bool(bebe_met and rapha_met and house_complete and bedtime_on_time and self_care_done)
