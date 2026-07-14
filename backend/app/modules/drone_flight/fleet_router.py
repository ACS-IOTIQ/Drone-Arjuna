"""
Fleet Router
============
Multi-drone -> target assignment (ported from the Q-SWARM prototype).

Given a set of active drones (current lat/lon pulled from the live
telemetry hot-cache) and a set of mission targets, finds an assignment
of drones to targets that minimises total travel distance.

Solvers:
  * OR-Tools CP-SAT   -- exact, classical, ALWAYS the default. No qubit
    budget limit, so the whole fleet is solved in one shot.
  * QAOA on Qiskit Aer -- optional, experimental (use_quantum=True).
    qiskit/qiskit-aer/scipy are NOT hard requirements of this backend;
    they are imported lazily so a deployment without them still runs
    fine on the classical path. Enable with:
        pip install qiskit qiskit-aer scipy
    Because the simulator can't handle many qubits, the quantum path
    decomposes the fleet into <=qubit_budget sub-problems first.

Distinct from mission_planner.py: that file plans ONE drone's route
through waypoints. This module decides WHICH drone gets WHICH target,
before any Mission/Waypoint rows exist.
"""
import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import structlog
from fastapi import HTTPException
from ortools.sat.python import cp_model
from pydantic import BaseModel

log = structlog.get_logger()

LatLon = tuple[float, float]


# ══════════════════════════════════════════════════════════════════
# Request / response schemas
# ══════════════════════════════════════════════════════════════════

class TargetPoint(BaseModel):
    id: str
    lat: float
    lon: float


class FleetAssignRequest(BaseModel):
    drone_instance_ids: Optional[list[int]] = None  # None = all connected drones
    targets: list[TargetPoint]
    qubit_budget: int = 12          # only used when use_quantum=True
    use_quantum: bool = False       # default to classical for operational safety


# ══════════════════════════════════════════════════════════════════
# Assignment QUBO
# ══════════════════════════════════════════════════════════════════

def _euclid_m(a: LatLon, b: LatLon) -> float:
    """Flat-earth distance in metres. Accurate for fleet-local ranges (<~50 km)."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    dy = (b[0] - a[0]) * m_per_deg_lat
    dx = (b[1] - a[1]) * m_per_deg_lon
    return math.hypot(dx, dy)


@dataclass
class AssignmentProblem:
    """Drone -> target assignment instance. Positions are (lat, lon)."""
    drones: list[LatLon]
    targets: list[LatLon]
    D: int = field(init=False)
    W: int = field(init=False)
    n: int = field(init=False)
    cost: list[list[float]] = field(init=False)
    penalty: float = field(init=False)

    def __post_init__(self):
        self.D = len(self.drones)
        self.W = len(self.targets)
        self.n = self.D * self.W
        self.cost = [[_euclid_m(self.drones[i], self.targets[j]) for j in range(self.W)]
                     for i in range(self.D)]
        cmax = max((max(row) for row in self.cost), default=0.0)
        self.penalty = 2.0 * cmax * self.W if cmax else 1.0

    def var(self, i: int, j: int) -> int:
        return i * self.W + j

    def build_qubo(self) -> dict[tuple[int, int], float]:
        Q: dict[tuple[int, int], float] = {}

        def add(p, q, v):
            key = (p, q) if p <= q else (q, p)
            Q[key] = Q.get(key, 0.0) + v

        for i in range(self.D):
            for j in range(self.W):
                add(self.var(i, j), self.var(i, j), self.cost[i][j])

        for j in range(self.W):
            for i in range(self.D):
                p = self.var(i, j)
                add(p, p, self.penalty * (1.0 - 2.0))
            for i, k in itertools.combinations(range(self.D), 2):
                add(self.var(i, j), self.var(k, j), self.penalty * 2.0)
        return Q

    def energy(self, bits: list[int]) -> float:
        e = 0.0
        for (p, q), v in self.build_qubo().items():
            e += v * bits[p] if p == q else v * bits[p] * bits[q]
        return e

    def decode(self, bits: list[int]) -> dict[int, list[int]]:
        """{target index j: [drone indices i]}"""
        return {j: [i for i in range(self.D) if bits[self.var(i, j)] == 1]
                for j in range(self.W)}

    def is_feasible(self, bits: list[int]) -> bool:
        return all(len(v) == 1 for v in self.decode(bits).values())

    def total_cost_m(self, bits: list[int]) -> float:
        return sum(self.cost[i][j] for i in range(self.D) for j in range(self.W)
                   if bits[self.var(i, j)] == 1)


# ══════════════════════════════════════════════════════════════════
# Classical solver (default)
# ══════════════════════════════════════════════════════════════════

def classical_assignment(problem: AssignmentProblem) -> tuple[list[int], float, float]:
    """Exact solve via OR-Tools CP-SAT. Returns (bits, total_cost_m, solve_ms)."""
    model = cp_model.CpModel()
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(problem.D) for j in range(problem.W)}

    for j in range(problem.W):
        model.Add(sum(x[(i, j)] for i in range(problem.D)) == 1)

    SCALE = 100  # metres -> integer units for CP-SAT
    model.Minimize(sum(int(problem.cost[i][j] * SCALE) * x[(i, j)]
                       for i in range(problem.D) for j in range(problem.W)))

    solver = cp_model.CpSolver()
    t0 = time.perf_counter()
    status = solver.Solve(model)
    ms = (time.perf_counter() - t0) * 1000

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise HTTPException(422, "No feasible fleet assignment found for the given drones/targets")

    bits = [0] * problem.n
    for i in range(problem.D):
        for j in range(problem.W):
            if solver.Value(x[(i, j)]) == 1:
                bits[problem.var(i, j)] = 1
    return bits, problem.total_cost_m(bits), ms


# ══════════════════════════════════════════════════════════════════
# Quantum solver (experimental, opt-in)
# ══════════════════════════════════════════════════════════════════

def quantum_assignment(problem: AssignmentProblem, p: int = 3) -> tuple[list[int], float, float]:
    """QAOA on Qiskit Aer. Lazily imports qiskit/qiskit-aer/scipy so they stay optional deps."""
    try:
        from qiskit import QuantumCircuit
        from qiskit_aer import AerSimulator
        from scipy.optimize import minimize
    except ImportError as e:
        raise HTTPException(
            501,
            "Quantum backend not installed. Run: pip install qiskit qiskit-aer scipy",
        ) from e

    n = problem.n
    ising, _offset = _qubo_to_ising(problem.build_qubo(), n)
    sim = AerSimulator(seed_simulator=7)

    def build_circuit(gammas, betas):
        qc = QuantumCircuit(n)
        qc.h(range(n))
        for layer in range(p):
            g = gammas[layer]
            for pauli, coeff in ising:
                zpos = [i for i, ch in enumerate(reversed(pauli)) if ch == "Z"]
                if len(zpos) == 1:
                    qc.rz(2 * coeff * g, zpos[0])
                elif len(zpos) == 2:
                    a, b = zpos
                    qc.cx(a, b)
                    qc.rz(2 * coeff * g, b)
                    qc.cx(a, b)
            beta = betas[layer]
            for i in range(n):
                qc.rx(2 * beta, i)
        qc.measure_all()
        return qc

    def sample(params):
        gammas, betas = params[:p], params[p:]
        return sim.run(build_circuit(gammas, betas), shots=2048).result().get_counts()

    def expected_energy(params):
        counts = sample(params)
        total, e = 0, 0.0
        for bitstr, c in counts.items():
            bits = [int(b) for b in reversed(bitstr)]
            e += problem.energy(bits) * c
            total += c
        return e / total

    rng = np.random.default_rng(1)
    x0 = rng.uniform(0, np.pi, size=2 * p)
    t0 = time.perf_counter()
    res = minimize(expected_energy, x0, method="COBYLA", options={"maxiter": 150})
    ms = (time.perf_counter() - t0) * 1000

    ranked = sorted(sample(res.x).items(), key=lambda kv: -kv[1])
    best_bits, best_e = None, float("inf")
    for bitstr, _ in ranked:
        bits = [int(b) for b in reversed(bitstr)]
        e = problem.energy(bits)
        if e < best_e:
            best_e, best_bits = e, bits
    return best_bits, problem.total_cost_m(best_bits), ms


def _qubo_to_ising(Q: dict[tuple[int, int], float], n: int):
    """QUBO (x in {0,1}) -> Ising Hamiltonian (z in {+1,-1}) via x = (1-z)/2."""
    h = np.zeros(n)
    J = np.zeros((n, n))
    for (p, q), v in Q.items():
        if p == q:
            h[p] += -v / 2.0
        else:
            h[p] += -v / 4.0
            h[q] += -v / 4.0
            J[p, q] += v / 4.0
    terms = []
    for i in range(n):
        if abs(h[i]) > 1e-12:
            s = ["I"] * n
            s[i] = "Z"
            terms.append(("".join(reversed(s)), h[i]))
    for i in range(n):
        for j in range(i + 1, n):
            if abs(J[i, j]) > 1e-12:
                s = ["I"] * n
                s[i] = "Z"
                s[j] = "Z"
                terms.append(("".join(reversed(s)), J[i, j]))
    return terms, 0.0


# ══════════════════════════════════════════════════════════════════
# Fleet decomposition (quantum path only — CP-SAT has no qubit limit)
# ══════════════════════════════════════════════════════════════════

def decompose_fleet_indices(
    drones: list[LatLon], targets: list[LatLon], qubit_budget: int = 12,
) -> list[tuple[list[int], list[int]]]:
    """
    Splits into sub-problems of <= qubit_budget qubits by geographic
    clustering of targets, keeping the nearest drones to each cluster.
    Returns (drone_indices, target_indices) pairs into the ORIGINAL lists
    so callers can map QAOA results back to real drone/target identities.
    """
    D, W = len(drones), len(targets)
    if D * W <= qubit_budget:
        return [(list(range(D)), list(range(W)))]

    d_sub = min(D, max(2, int(math.isqrt(qubit_budget))))
    w_sub = max(1, qubit_budget // d_sub)

    cy = sum(p[0] for p in targets) / W
    cx = sum(p[1] for p in targets) / W
    ordered = sorted(range(W), key=lambda j: math.atan2(targets[j][0] - cy, targets[j][1] - cx))

    subs = []
    for start in range(0, W, w_sub):
        t_idx = ordered[start:start + w_sub]
        tgt = [targets[j] for j in t_idx]
        gy = sum(p[0] for p in tgt) / len(tgt)
        gx = sum(p[1] for p in tgt) / len(tgt)
        d_idx = sorted(range(D), key=lambda i: _euclid_m(drones[i], (gy, gx)))[:d_sub]
        subs.append((d_idx, t_idx))
    return subs
