"""
shield_adapter.py — wrapper LOCALE (in-process) attorno a un SimAdapter,
usando ShieldCore (shield_core.py) invece del Gateway HTTP
(safety_shield_adapter.py, gia' presente, usa POST /v1/verify). Stessa
interfaccia astratta, stesso scopo (verificare ogni attuazione fisica
prima che raggiunga l'adapter reale), nessuna rete -- per una demo
completamente offline con un solo processo.

Quale dei due usare (mutuamente esclusivi, vedi adapter_manager.py):
    - safety_shield_adapter.py (remoto)  -- centralizzato, multi-tenant,
      coerente col prodotto Agent Gateway (safety-shield-platform).
    - shield_adapter.py (locale, questo file) -- zero dipendenze esterne,
      utile per una demo/video senza dover far girare un secondo servizio.
"""

import logging
from typing import Optional

from adapters.shield_core import ShieldCore
from adapters.sim_adapter import ActionResult, SimAdapter

logger = logging.getLogger(__name__)


class ShieldAdapter(SimAdapter):
    """Transparent proxy: inoltra tutto all'adapter reale, tranne i metodi
    di attuazione fisica, verificati prima da ShieldCore.evaluate_command()."""

    def __init__(self, inner: SimAdapter, shield: ShieldCore, robot_id: str = "UAV_1") -> None:
        self._inner = inner
        self._shield = shield
        self._robot_id = robot_id
        self.name = f"shielded-local({inner.name})"
        self.description = f"Local Safety Shield wrapper around {inner.description}"
        self.supported_vehicles = inner.supported_vehicles

    def _verify(self, tool: str, params: dict) -> Optional[ActionResult]:
        verdict = self._shield.evaluate_command(tool, {**params, "robot_id": self._robot_id})
        if not verdict.approved:
            logger.warning(f"[ShieldAdapter] BLOCCATO: {tool}({params}) — {verdict.reason}")
            return ActionResult(success=False, message=f"Blocked by Safety Shield: {verdict.reason}")
        logger.info(f"[ShieldAdapter] approvato: {tool}({params})")
        return None

    # ── attuazione fisica: verificata ────────────────────────────────
    def arm(self) -> ActionResult:
        return self._verify("arm", {}) or self._inner.arm()

    def disarm(self) -> ActionResult:
        return self._verify("disarm", {}) or self._inner.disarm()

    def takeoff(self, altitude: float = 5.0) -> ActionResult:
        return self._verify("takeoff", {"altitude": altitude}) or self._inner.takeoff(altitude)

    def land(self) -> ActionResult:
        return self._verify("land", {}) or self._inner.land()

    def fly_to_ned(self, north: float, east: float, down: float, speed: float = 2.0) -> ActionResult:
        args = {"north": north, "east": east, "down": down, "speed": speed}
        return self._verify("fly_to_ned", args) or self._inner.fly_to_ned(north, east, down, speed)

    def hover(self, duration: float = 5.0) -> ActionResult:
        return self._verify("hover", {"duration": duration}) or self._inner.hover(duration)

    def return_to_launch(self) -> ActionResult:
        return self._verify("return_to_launch", {}) or self._inner.return_to_launch()

    def fly_to_gps(self, lat: float, lon: float, alt: float, speed: float = 2.0) -> ActionResult:
        args = {"lat": lat, "lon": lon, "alt": alt, "speed": speed}
        return self._verify("fly_to_gps", args) or self._inner.fly_to_gps(lat, lon, alt, speed)

    def set_heading(self, heading_deg: float) -> ActionResult:
        return self._verify("set_heading", {"heading_deg": heading_deg}) or self._inner.set_heading(heading_deg)

    def set_velocity_body(self, forward: float, right: float, down: float, yaw_rate: float = 0.0) -> ActionResult:
        args = {"forward": forward, "right": right, "down": down, "yaw_rate": yaw_rate}
        return self._verify("set_velocity_body", args) or self._inner.set_velocity_body(forward, right, down, yaw_rate)

    def orbit(self, radius: float, velocity: float, center=None) -> ActionResult:
        return self._verify("orbit", {"radius": radius, "velocity": velocity}) or self._inner.orbit(radius, velocity, center)

    # goto_waypoints: non sovrascritto di proposito -- il default di
    # SimAdapter chiama self.fly_to_ned() per ogni waypoint, quindi
    # ereditandolo ogni tappa passa comunque dalla verifica.

    # ── tutto il resto: pass-through diretto ─────────────────────────
    def connect(self, connection_str: str = "", timeout: float = 15.0) -> bool:
        return self._inner.connect(connection_str, timeout)

    def disconnect(self) -> None:
        return self._inner.disconnect()

    def is_connected(self) -> bool:
        return self._inner.is_connected()

    def get_state(self):
        return self._inner.get_state()

    def get_position(self):
        return self._inner.get_position()

    def get_gps(self):
        return self._inner.get_gps()

    def get_battery(self) -> tuple:
        return self._inner.get_battery()

    def is_armed(self) -> bool:
        return self._inner.is_armed()

    def is_in_air(self) -> bool:
        return self._inner.is_in_air()

    def stop_velocity(self) -> ActionResult:
        return self._inner.stop_velocity()
