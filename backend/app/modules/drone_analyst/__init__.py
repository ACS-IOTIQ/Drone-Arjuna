
# ═══════════════════════════════════════════════════════════════
# app/modules/drone_analyst/__init__.py
# ═══════════════════════════════════════════════════════════════
"""
Drone Analyst Module  [V1 stub — full implementation in V2]
====================
AI/CV intelligence analysis — object detection, change detection,
video motion analysis, and automated reporting.
V2 will add YOLOv8, PyTorch pipelines, and ONNX Runtime inference.

Public API:
    router  — FastAPI stub endpoints at /api/analyst/
"""
from app.modules.drone_analyst.router import router

__all__ = ["router"]