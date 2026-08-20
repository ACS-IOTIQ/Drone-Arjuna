"""Launch the backend natively on Windows without Docker (uvloop is Linux/Mac-only)."""
import asyncio
import os
import sys
import types

os.environ.setdefault("ENV_FILE", ".env.native")

uvloop_stub = types.ModuleType("uvloop")
uvloop_stub.EventLoopPolicy = asyncio.DefaultEventLoopPolicy
sys.modules["uvloop"] = uvloop_stub

import enum
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass
    enum.StrEnum = StrEnum

from dotenv import load_dotenv
load_dotenv(".env.native", override=True)

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
