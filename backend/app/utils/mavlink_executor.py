"""
Dedicated thread pool for blocking pymavlink I/O (recv_match, heartbeat_send,
mavlink_connection, broadcast sends).

asyncio.to_thread / loop.run_in_executor(None, ...) both submit to Python's
shared default ThreadPoolExecutor (min(32, cpu_count + 4) threads), which is
also used by MinIO/boto3 calls (app.core.storage) and the backup dump/upload
path (app.core.backup). At fleet scale, every connected drone's read loop
submits a blocking recv_match call to that pool roughly once per second (plus
one broadcast send per state update for simulated flights) — under load this
competes with backup/storage threads for the same limited pool, adding
latency/jitter to telemetry reads that has nothing to do with actual MAVLink
I/O being slow.

This pool is sized generously per expected fleet size and used only for
MAVLink-related blocking calls, so it can never be starved by unrelated I/O
and vice versa.
"""
from concurrent.futures import ThreadPoolExecutor

# One thread per connected drone (read loop) plus headroom for connect-time
# and broadcast-send bursts. 64 comfortably covers fleets well beyond what a
# single GCS instance is expected to manage.
MAX_WORKERS = 64

mavlink_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="mavlink-io")
