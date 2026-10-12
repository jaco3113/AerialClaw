"""
test_demo_scenario.py — demo a due run, Safety Shield LOCALE (nessuna rete).

Missione di pattuglia rettangolare 200m x 200m (geofence N/E in [-100,100]),
quota max 50m -- entro i limiti statici del flight envelope YAML esistente
di AerialClaw (config/safety_config.yaml), che quindi approverebbe
normalmente ogni comando di questa missione.

Dopo il secondo waypoint, inietta un evento esterno (shield_events.json)
che chiude un cerchio di raggio 20m centrato esattamente sul terzo
waypoint -- simula un NOTAM/chiusura spazio aereo comparsa a missione gia'
in corso.

Uso (AerialClaw deve essere gia' in esecuzione su http://127.0.0.1:5001,
vedi i due comandi di avvio sotto):

    # run (a) — baseline, senza Shield
    SIM_ADAPTER=mock python server.py &
    python3 test_demo_scenario.py baseline

    # run (b) — con Shield locale
    SIM_ADAPTER=mock SAFETY_SHIELD_LOCAL=1 \\
        SAFETY_SHIELD_MAX_ALTITUDE_M=50 \\
        SAFETY_SHIELD_GEOFENCE_MIN_NORTH=-100 SAFETY_SHIELD_GEOFENCE_MAX_NORTH=100 \\
        SAFETY_SHIELD_GEOFENCE_MIN_EAST=-100 SAFETY_SHIELD_GEOFENCE_MAX_EAST=100 \\
        python server.py &
    python3 test_demo_scenario.py shielded
"""

import json
import sys
import time
from pathlib import Path

import socketio

AERIALCLAW = "http://127.0.0.1:5001"
EVENTS_FILE = Path("shield_events.json")

WAYPOINTS = [
    {"north": 40, "east": 40, "down": -20},
    {"north": 40, "east": -40, "down": -20},
    {"north": -40, "east": -40, "down": -20},  # <- dentro la zona che verra' chiusa
    {"north": -40, "east": 40, "down": -20},
]

EVENT = {"label": "Evento esterno: elicottero in zona", "center_north": -40, "center_east": -40, "radius_m": 20}


def inject_event():
    """Scrive l'evento nel file che ShieldCore osserva (adapters/shield_core.py,
    _sync_events_file) -- lo stand-in piu' semplice per "un evento arriva da
    un processo esterno" senza dover aprire una porta di rete solo per questo."""
    EVENTS_FILE.write_text(json.dumps([EVENT]))
    print(f"[EVENT] iniettato in {EVENTS_FILE}: {EVENT}")


def run_mission(label: str):
    sio = socketio.Client()
    results = []

    @sio.on("skill_result")
    def on_result(data):
        results.append(data)

    sio.connect(AERIALCLAW)

    def exec_skill(skill_name, parameters, note=""):
        results.clear()
        sio.emit("execute_skill", {"robot_id": "UAV_1", "skill_name": skill_name, "parameters": parameters})
        time.sleep(1.2)
        r = results[0] if results else {"ok": None, "error": "nessuna risposta"}
        status = "✅ ESEGUITO" if r.get("ok") else "🛑 BLOCCATO/FALLITO"
        line = f"  [{label}] {note or skill_name}({parameters}) -> {status}"
        if r.get("error"):
            line += f" — {r.get('error')}"
        print(line)
        return r

    print(f"\n===== RUN: {label.upper()} =====")
    exec_skill("takeoff", {"altitude": 20.0}, "takeoff 20m")
    exec_skill("fly_to", {"target_position": [WAYPOINTS[0]["north"], WAYPOINTS[0]["east"], WAYPOINTS[0]["down"]], "speed": 15.0}, "waypoint 1")
    exec_skill("fly_to", {"target_position": [WAYPOINTS[1]["north"], WAYPOINTS[1]["east"], WAYPOINTS[1]["down"]], "speed": 15.0}, "waypoint 2")

    print(f"  [{label}] --- a meta' missione: evento esterno iniettato ---")
    inject_event()

    exec_skill("fly_to", {"target_position": [WAYPOINTS[2]["north"], WAYPOINTS[2]["east"], WAYPOINTS[2]["down"]], "speed": 15.0}, "waypoint 3 (ora dentro la zona chiusa)")
    exec_skill("fly_to", {"target_position": [WAYPOINTS[3]["north"], WAYPOINTS[3]["east"], WAYPOINTS[3]["down"]], "speed": 15.0}, "waypoint 4")
    exec_skill("land", {}, "land")

    sio.disconnect()


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    run_mission(label)
