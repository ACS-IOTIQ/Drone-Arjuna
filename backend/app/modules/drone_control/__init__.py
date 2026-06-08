"""
Drone Control Module
====================
Primary interface between ground operators and MAVLink-compatible drones.

Public API exposed at package level so other modules import from here:

    from app.modules.drone_control import mavlink_manager, data_recorder

Internal submodules:
    mavlink_manager      — async multi-drone connection pool
    telemetry_processor  — MAVLink message → state dict parsing
    command_controller   — validation, encoding, ACK tracking per drone
    state_manager        — in-memory hot state + subscriber callbacks
    health_monitor       — threshold alerts + auto-RTL failsafe
    data_recorder        — batched async writes to TimescaleDB
    router               — FastAPI REST + WebSocket endpoints
"""

from app.modules.drone_control.mavlink_manager import mavlink_manager
from app.modules.drone_control.data_recorder import data_recorder
from app.modules.drone_control.command_controller import CommandController, CommandResult, CommandRecord
from app.modules.drone_control.state_manager import StateManager

__all__ = [
    "mavlink_manager",
    "data_recorder",
    "CommandController",
    "CommandResult",
    "CommandRecord",
    "StateManager",
]