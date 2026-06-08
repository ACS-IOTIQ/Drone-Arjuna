# ═══════════════════════════════════════════════════════════════
# app/modules/drone_master/__init__.py
# ═══════════════════════════════════════════════════════════════
"""
Drone Master Module
===================
Central repository for all master data — drone types, payload types,
communication link configurations, and configuration templates.

Public API:
    router  — FastAPI CRUD endpoints at /api/master/
"""
from app.modules.drone_master.router import router

__all__ = ["router"]
