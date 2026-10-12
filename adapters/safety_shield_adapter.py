"""
safety_shield_adapter.py — Safety Shield / Agent Gateway integration.

Wraps ANY SimAdapter (mock, PX4, AirSim, ...) so that every physical
actuation call is verified by an independent Safety Shield Gateway
(POST /v1/verify) before it reaches the real adapter — the same "verify
right before the command reaches the actuator" principle used throughout
the Safety Shield project (see core/router.py in drone-safety-shield and
gateway_core.py in safety-shield-platform).

Installed once, in adapter_manager.init_adapter(), this covers every hard
skill (motor_skills.py) transparently: skills only ever call
adapter_manager.get_adapter(), never a concrete adapter class directly
(see sim_adapter.py's own docstring), so wrapping happens in exactly one
place regardless of which backend (mock/px4/airsim) is active.

Read-only methods (get_state, get_position, get_battery, is_armed,
is_in_air, connect/disconnect) pass straight through unmodified: verifying
"where am I" makes no sense, only "what am I about to do" does.

Enable by setting, in .env:
    SAFETY_SHIELD_URL=http://127.0.0.1:8000
    SAFETY_SHIELD_API_KEY=ssk_...
If either is unset, adapter_manager skips wrapping entirely — zero
overhead and zero behavior change for anyone not using the Shield.

Fail-closed: if the Gateway is unreachable or errors, the command is
denied, never silently allowed through. A drone that cannot reach its
safety layer should not be flying unsupervised.
"""

import logging
from typing import Optional

import requests

from adapters.sim_adapter import ActionResult, SimAdapter

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 3.0


class SafetyShieldAdapter(SimAdapter):
    """Transparent proxy: forwards everything to the wrapped adapter,
    except the physical-actuation methods below, which are checked against
    POST /v1/verify first."""

    def __init__(
        self,
        inner: SimAdapter,
        gateway_url: str,
        api_key: str,
        robot_id: str = "UAV_1",
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._inner = inner
        self._gateway_url = gateway_url.rstrip("/")
        self._api_key = api_key
        self._robot_id = robot_id
        self._timeout_s = timeout_s
        self.name = f"shielded({inner.name})"
        self.description = f"Safety Shield wrapper around {inner.description}"
        self.supported_vehicles = inner.supported_vehicles

    def _verify(self, tool_name: str, arguments: dict) -> Optional[ActionResult]:
        """Returns a denial ActionResult if the Gateway rejects the
        command, or None if approved (clear to call the real adapter)."""
        try:
            resp = requests.post(
                f"{self._gateway_url}/v1/verify",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"tool_name": tool_name, "arguments": {**arguments, "robot_id": self._robot_id}},
                timeout=self._timeout_s,
            )
            data = resp.json()
        except Exception as e:
            logger.error(f"[SafetyShield] gateway unreachable ({e}) — denying by default (fail-closed)")
            return ActionResult(success=False, message=f"Safety Shield gateway unreachable: {e}")

        if not data.get("approved", False):
            reason = data.get("reason", "denied by Safety Shield")
            logger.warning(f"[SafetyShield] BLOCKED: {tool_name}({arguments}) — {reason}")
            return ActionResult(success=False, message=f"Blocked by Safety Shield: {reason}")

        logger.info(f"[SafetyShield] approved: {tool_name}({arguments})")
        return None

    # ── physical actuation: verified ────────────────────────────────
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

    # goto_waypoints intentionally NOT overridden: SimAdapter's own default
    # implementation calls self.fly_to_ned() per waypoint, so inheriting it
    # here means every waypoint is verified individually, for free.

    # ── everything else: direct pass-through (state reads, connection) ──
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
