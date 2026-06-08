
# ═══════════════════════════════════════════════════════════════
# app/modules/drone_flight/__init__.py
# ═══════════════════════════════════════════════════════════════
"""
Drone Flight Module
===================
Mission planning, execution, and real-time visualization.

Public API:
    router       — FastAPI endpoints at /api/flight/
    geo_service  — Haversine distance and mission summary utilities
"""
from app.modules.drone_flight.router import router
from app.modules.drone_flight.geo_service import compute_mission_summary

__all__ = ["router", "compute_mission_summary"]

