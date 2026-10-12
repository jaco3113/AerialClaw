"""
shield_core.py — Safety Shield in-process, locale (nessuna rete).

Versione standalone di gateway_core.py (prodotto safety-shield-platform):
stessa logica di verifica (blacklist, rate limit, quota massima, geofence
rettangolare, zone vietate temporanee), ma puramente in-process -- nessun
server, nessun database, nessuna chiamata HTTP. Pensata per una demo
offline con un solo processo, dove far girare un secondo servizio
(il Gateway di safety_shield_adapter.py) non e' necessario o desiderato.

Iniezione di eventi esterni (NOTAM/chiusura spazio aereo): handle_external_
event() e' un metodo Python diretto, chiamabile nello stesso processo
(es. da un test). Per iniettare un evento da UN PROCESSO ESTERNO (come lo
script della demo, che deve avviare AerialClaw come sottoprocesso separato)
senza dover aprire una porta di rete solo per questo, ShieldCore osserva
un file JSON (default: shield_events.json) e lo rilegge ad ogni
evaluate_command() se e' cambiato -- un file e' lo stand-in piu' semplice
per "un evento arriva da fuori" in una demo locale; in produzione sarebbe
un vero feed NOTAM o un comando operatore, non un file.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Set, Tuple


@dataclass
class ShieldVerdict:
    approved: bool
    reason: Optional[str] = None


@dataclass
class NoFlyZone:
    label: str
    center_north: float
    center_east: float
    radius_m: float


class ShieldCore:
    """Stato del vincolo in-memory -- stessa forma di gateway_core.py /
    models.ApiKey (safety-shield-platform), senza il livello DB/FastAPI."""

    def __init__(
        self,
        max_altitude_m: Optional[float] = None,
        geofence: Optional[Tuple[float, float, float, float]] = None,  # (min_north, max_north, min_east, max_east)
        denied_tools: Optional[Set[str]] = None,
        rate_limit_per_minute: Optional[int] = None,
        events_file: Optional[str] = None,
    ) -> None:
        self.max_altitude_m = max_altitude_m
        self.geofence = geofence
        self.denied_tools = denied_tools or set()
        self.rate_limit_per_minute = rate_limit_per_minute
        self._no_fly_zones: list = []
        self._call_timestamps: list = []
        self._events_file = Path(events_file) if events_file else None
        self._events_file_mtime: Optional[float] = None
        self.log: list = []  # audit trail in-memory, stesso spirito di GatewayCall

    # ── iniezione eventi esterni ──────────────────────────────────────
    def handle_external_event(self, label: str, center_north: float, center_east: float, radius_m: float) -> None:
        self._no_fly_zones.append(NoFlyZone(label, center_north, center_east, radius_m))

    def _sync_events_file(self) -> None:
        if self._events_file is None or not self._events_file.exists():
            return
        mtime = self._events_file.stat().st_mtime
        if mtime == self._events_file_mtime:
            return  # nessuna modifica dall'ultima lettura
        self._events_file_mtime = mtime
        try:
            events = json.loads(self._events_file.read_text())
        except (json.JSONDecodeError, OSError):
            return
        existing = {(z.label, z.center_north, z.center_east, z.radius_m) for z in self._no_fly_zones}
        for e in events:
            key = (e["label"], e["center_north"], e["center_east"], e["radius_m"])
            if key not in existing:
                self.handle_external_event(e["label"], e["center_north"], e["center_east"], e["radius_m"])

    # ── verifica ──────────────────────────────────────────────────────
    def evaluate_command(self, tool: str, params: dict) -> ShieldVerdict:
        self._sync_events_file()

        if not tool:
            return self._record(ShieldVerdict(False, "tool mancante"), tool, params)

        if tool in self.denied_tools:
            return self._record(ShieldVerdict(False, f"tool '{tool}' in blacklist"), tool, params)

        if self.rate_limit_per_minute is not None:
            now = time.time()
            self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]
            if len(self._call_timestamps) >= self.rate_limit_per_minute:
                return self._record(
                    ShieldVerdict(False, f"rate limit superato ({self.rate_limit_per_minute}/min)"), tool, params
                )
            self._call_timestamps.append(now)

        altitude = self._command_altitude_m(tool, params)
        if self.max_altitude_m is not None and altitude is not None and altitude > self.max_altitude_m:
            return self._record(
                ShieldVerdict(False, f"quota richiesta {altitude:.1f}m supera il limite di {self.max_altitude_m:.1f}m"),
                tool, params,
            )

        if self.geofence is not None and tool == "fly_to_ned":
            min_n, max_n, min_e, max_e = self.geofence
            n, e = params.get("north"), params.get("east")
            if n is not None and e is not None and not (min_n <= n <= max_n and min_e <= e <= max_e):
                return self._record(
                    ShieldVerdict(False, f"posizione (N={n:.1f},E={e:.1f}) fuori dal geofence"), tool, params
                )

        if tool == "fly_to_ned":
            n, e = params.get("north"), params.get("east")
            if n is not None and e is not None:
                for zone in self._no_fly_zones:
                    dist = ((n - zone.center_north) ** 2 + (e - zone.center_east) ** 2) ** 0.5
                    if dist <= zone.radius_m:
                        return self._record(
                            ShieldVerdict(False, f"zona temporaneamente interdetta: '{zone.label}' (raggio {zone.radius_m:.0f}m)"),
                            tool, params,
                        )

        return self._record(ShieldVerdict(True), tool, params)

    @staticmethod
    def _command_altitude_m(tool: str, params: dict) -> Optional[float]:
        """NED: altitude = -down, stessa convenzione di adapters/sim_adapter.py."""
        if tool == "takeoff":
            return params.get("altitude")
        if tool == "fly_to_ned":
            down = params.get("down")
            return -down if down is not None else None
        return None

    def _record(self, verdict: ShieldVerdict, tool: str, params: dict) -> ShieldVerdict:
        self.log.append({
            "timestamp": time.time(),
            "tool": tool,
            "params": params,
            "approved": verdict.approved,
            "reason": verdict.reason,
        })
        return verdict
