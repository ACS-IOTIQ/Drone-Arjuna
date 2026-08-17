# DroneArjuna (DA) — Project Plan: Closing Phase 3–6 Gaps
**ACS Technologies Limited | RESTRICTED / CONFIDENTIAL**
**Plan period:** 10 August 2026 – 30 September 2026
**Baseline:** DA-Implementation-Status.pdf (5 August 2026)
**Team:** Chandra Sekhar (Backend Lead), Vaishnavi (Backend), Indra (Frontend)

---

## 1. Purpose

This plan sequences the work needed to close every gap identified in the As-Built Implementation
Status Report (Phases 3–6) into two staffing windows:

- **Window A — 10 Aug to 31 Aug:** Vaishnavi available at **25% capacity**. Chandra Sekhar
  covers the remaining backend load; Indra runs frontend independently.
- **Window B — 1 Sep onward:** Vaishnavi returns to **full capacity**. Backend work is split
  in parallel between Chandra Sekhar and Vaishnavi; Indra continues frontend.

Effort is expressed in **person-days (PD)** — one PD = one person working one day at 100%
capacity. Vaishnavi's 25% availability in Window A means her *elapsed* calendar time to deliver
a task is ~4x its PD estimate.

---

## 2. Gap List with Effort Estimates

| # | Gap (from Status Report §6) | Track | Effort (PD) | Depends on |
|---|---|---|---|---|
| G1 | 3D visualisation scaffold (Cesium/terrain, 3D drone tracking) | Frontend | 10 | none |
| G2 | Telemetry replay player (3D + timeline scrub) | Frontend | 5 | G1 |
| G3 | Drone Inventory — full knowledge-base workflow (linked records, cross-refs, browse UI) | Backend + Frontend | 8 (5 BE / 3 FE) | none |
| G4 | Drone Analyst — background worker infrastructure (job queue consumer) | Backend | 6 | none |
| G5 | Drone Analyst — object-detection inference (YOLOv8 integration) | Backend | 8 | G4 |
| G6 | Drone Analyst — video-frame extraction pipeline | Backend | 5 | G4 |
| G7 | Drone Analyst — change-detection module | Backend | 6 | G5, G6 |
| G8 | Object storage wired into code (MinIO upload for imagery/video/detections) | Backend | 4 | none |
| G9 | Drone Analyst frontend workspace (job launch, results viewer, telemetry dashboard) | Frontend | 8 | G4, G5 |
| G10 | Automated test coverage — raise to ≥80% verified (coverage tooling + gap-fill tests) | Backend + Frontend | 6 (4 BE / 2 FE) | ongoing |
| G11 | CI pipeline (lint, type-check, test run, build, on PR) | Backend + Frontend | 4 | none |
| G12 | Accessibility pass (WCAG on all 5 workspaces) | Frontend | 5 | none |
| G13 | Load testing (telemetry pipeline + API under multi-drone load) | Backend | 4 | G4–G8 stable |
| G14 | Frontend automated test suite (currently zero frontend tests exist) | Frontend | 6 | none |

**Total effort:** Backend ≈ 33 PD · Frontend ≈ 39 PD · Shared/overlap ≈ 5 PD

---

## 3. Capacity Model

| Person | Window A (10–31 Aug, 16 working days) | Window B (1–30 Sep, 22 working days) |
|---|---|---|
| Chandra Sekhar | 16 PD (100%) | 22 PD (100%) |
| Vaishnavi | 4 PD (25% of 16) | 22 PD (100%) |
| Indra | 16 PD (100%) | 22 PD (100%) |

Window A backend capacity (Chandra Sekhar + Vaishnavi) = **20 PD**.
Window B backend capacity (Chandra Sekhar + Vaishnavi) = **44 PD**.
Frontend capacity is Indra alone throughout: **16 PD (Window A) + 22 PD (Window B) = 38 PD**.

---

## 4. Phase Sequencing

### Window A — 10 Aug to 31 Aug (backend: Chandra Sekhar full + Vaishnavi 25%; frontend: Indra full)

Backend priority order (highest leverage / unblocks the most later work first):
1. **G4 — Analyst background worker infrastructure** (6 PD)
2. **G8 — Object storage wiring** (4 PD)
3. **G3 backend half — Inventory knowledge-base data/link model** (5 PD)
4. **G10 backend half — coverage tooling + first gap-fill pass** (4 PD, start only, continues into Window B)

Total backend load = 19 PD against 20 PD capacity — tight but fits, with Vaishnavi's 4 PD
absorbed into G4 (well-scoped, low-coordination-overhead task suited to fractional availability).

Frontend priority order:
1. **G1 — 3D visualisation scaffold** (10 PD)
2. **G14 — Frontend test suite scaffolding + first coverage pass** (6 PD, start)

Total frontend load = 16 PD against 16 PD capacity.

### Window B — 1 Sep to 30 Sep (backend: Chandra Sekhar + Vaishnavi both full; frontend: Indra full)

Backend priority order:
1. **G5 — Object-detection inference (YOLOv8)** (8 PD)
2. **G6 — Video-frame extraction pipeline** (5 PD)
3. **G7 — Change-detection module** (6 PD)
4. **G3 backend remainder** if not finished (buffer)
5. **G10 — finish coverage to ≥80%, verified** (remaining PD)
6. **G13 — Load testing** (4 PD)
7. **G11 backend half — CI pipeline (backend jobs)** (2 PD)

Total backend load ≈ 25–29 PD against 44 PD capacity — comfortable buffer for MAVLink/CV
integration risk (this is the highest-uncertainty work in the whole plan).

Frontend priority order:
1. **G2 — Telemetry replay player** (5 PD)
2. **G9 — Drone Analyst frontend workspace** (8 PD)
3. **G12 — Accessibility pass** (5 PD)
4. **G14 — finish frontend test suite** (remainder)
5. **G3 frontend half — Inventory knowledge-base browse UI** (3 PD)
6. **G11 frontend half — CI pipeline (frontend jobs)** (2 PD)

Total frontend load ≈ 23 PD against 22 PD capacity — essentially full; G14 remainder is the
flex item if anything slips.

---

## 5. Individual Task Plan — Window A (10 Aug – 1 Sep)

### Chandra Sekhar (Backend Lead) — 100% capacity, ~16 PD

| Dates | Task | Gap ref |
|---|---|---|
| Aug 10–13 | Design + implement Analyst job-queue consumer (RabbitMQ worker process, job state transitions: queued → running → done/failed) | G4 |
| Aug 14–17 | Wire MinIO object storage into Analyst job pipeline (upload source imagery, store object keys against job records) | G8 |
| Aug 18–21 | Drone Inventory knowledge-base data model: link table between drones/threats/payloads, cross-reference queries, backend endpoints | G3 (BE) |
| Aug 24–28 | Set up backend coverage tooling (pytest-cov + reporting), run baseline coverage report, begin closing gaps in weakest modules | G10 (BE, start) |
| Aug 31 | Review Vaishnavi's G4 sub-task output, integrate, buffer/catch-up day | — |

### Vaishnavi (Backend) — 25% capacity, ~4 PD spread across the window

| Dates (elapsed) | Task | Gap ref | PD |
|---|---|---|---|
| Aug 10–14 (partial days) | Job registry schema review + write unit tests for job state-transition logic (paired with Chandra Sekhar's G4 consumer) | G4 | 1.5 |
| Aug 17–21 (partial days) | Write integration tests for MinIO upload path (mock + real bucket test) | G8 | 1.5 |
| Aug 24–31 (partial days) | Document Analyst worker + object-storage design decisions in DA-DDD-001 addendum | G4/G8 | 1.0 |

*Rationale: Vaishnavi's fractional time is assigned to test-writing and documentation on
Chandra Sekhar's in-progress work rather than an independent task — this avoids context-switch
overhead that a standalone task would carry at 25% availability, and keeps her productive
without becoming a blocking dependency for anyone.*

### Indra (Frontend) — 100% capacity, ~16 PD

| Dates | Task | Gap ref |
|---|---|---|
| Aug 10–14 | Evaluate/scaffold Cesium integration into the Fly workspace; basic 3D terrain tile loading, camera controls | G1 |
| Aug 17–21 | 3D live drone tracking — render live telemetry positions as 3D entities on the Cesium globe, sync with existing 2D map state | G1 |
| Aug 24–26 | 3D visualisation polish: altitude exaggeration toggle, drone model/icon, mission waypoint overlay in 3D | G1 |
| Aug 27–31 | Frontend test suite scaffolding (Vitest + React Testing Library setup); first tests for Fleet workspace and shared components | G14 (start) |

---

## 6. Individual Task Plan — Window B (1 Sep – 30 Sep)

### Chandra Sekhar (Backend Lead) — 100% capacity, ~22 PD

| Dates | Task | Gap ref |
|---|---|---|
| Sep 1–4 | YOLOv8 model integration: load pretrained weights, inference endpoint wired to job worker | G5 |
| Sep 7–9 | Inference result → detection-result table persistence, confidence/bounding-box schema finalisation | G5 |
| Sep 10–14 | Video-frame extraction pipeline (ffmpeg-based frame sampling from uploaded video, feeding into inference queue) | G6 |
| Sep 15–17 | CI pipeline — backend jobs (lint, type-check via mypy/ruff, pytest run, Docker build) in GitHub Actions | G11 (BE) |
| Sep 18–21 | Load testing: multi-drone telemetry pipeline under simulated 10+ drone load, profile and fix bottlenecks found | G13 |
| Sep 22–25 | Change-detection module: pairwise frame/image comparison logic, threshold tuning | G7 |
| Sep 28–30 | Coverage gap-fill (final push to ≥80%), review Vaishnavi's parallel backend output, integration pass | G10 |

### Vaishnavi (Backend) — 100% capacity, ~22 PD, working in parallel with Chandra Sekhar

| Dates | Task | Gap ref |
|---|---|---|
| Sep 1–4 | Drone Inventory knowledge-base backend remainder: full-text cross-reference search across drones/threats/payloads, admin endpoints for managing links | G3 (BE remainder) |
| Sep 7–10 | Change-detection module — supporting utilities (image diff scoring, storage of before/after pairs) run in parallel with Chandra Sekhar's G7 core logic | G7 (support) |
| Sep 11–14 | Backend coverage gap-fill — target modules: drone_analyst, drone_inventory, mavlink_broadcaster edge cases | G10 |
| Sep 15–18 | Object-storage lifecycle: retention/cleanup policy for old job artifacts, presigned URL generation for frontend result viewing | G8 (hardening) |
| Sep 21–24 | Load testing support — write test harness/fixtures for simulated multi-drone load (Chandra Sekhar runs and profiles) | G13 (support) |
| Sep 25–30 | Analyst API polish: pagination on job/results list endpoints (closes the pagination gaps found in the earlier perf audit), final integration testing with Indra's Analyst UI (G9) | G10, backlog perf item |

### Indra (Frontend) — 100% capacity, ~22 PD

| Dates | Task | Gap ref |
|---|---|---|
| Sep 1–4 | Telemetry replay player: timeline scrub UI, playback controls, sync with 3D view from G1 | G2 |
| Sep 7–10 | Drone Analyst workspace — job launch UI (upload/select source, launch job, status polling) | G9 |
| Sep 11–14 | Drone Analyst workspace — results viewer (detection overlays, model registry browser, telemetry stats dashboard) | G9 |
| Sep 15–17 | CI pipeline — frontend jobs (lint, type-check, Vitest run, build) in GitHub Actions | G11 (FE) |
| Sep 18–22 | Accessibility pass across all 5 workspaces (keyboard nav, ARIA labels, contrast, screen-reader pass) | G12 |
| Sep 23–25 | Drone Inventory knowledge-base browse UI (cross-reference viewer consuming Vaishnavi's Sep 1–4 backend work) | G3 (FE) |
| Sep 28–30 | Frontend test suite — finish coverage on Fly/Plan/Monitor workspaces, close out G14 | G14 |

---

## 7. Milestones

| Date | Milestone |
|---|---|
| 21 Aug | Analyst job worker + object storage live end-to-end (backend) |
| 31 Aug | 3D visualisation scaffold usable in Fly workspace; Window A close-out review |
| 4 Sep | YOLOv8 inference producing real detection results on test imagery |
| 14 Sep | Change-detection + video pipeline functional; Analyst workspace UI usable end-to-end |
| 21 Sep | CI pipeline green on both backend and frontend; load test report delivered |
| 30 Sep | ≥80% verified coverage, accessibility pass complete, all Phase 3–5 gaps closed or explicitly deferred |

---

## 8. Risks & Notes

- **YOLOv8 integration (G5) is the highest-uncertainty item** — model performance on drone-specific
  imagery is unproven; if accuracy is poor, budget for an extra 3–5 PD in late September for
  retraining/fine-tuning, taken from the G13 load-testing buffer if needed.
- **Vaishnavi's Window A tasks are deliberately paired with Chandra Sekhar's**, not independent,
  because 25% availability spread over 3 weeks makes standalone ownership of a task with any
  external dependency high-risk for slippage.
- **3D visualisation (G1) has no backend dependency** and was scheduled first in Window A so Indra
  isn't blocked waiting on backend work at any point in the plan.
- **CI pipeline (G11) is intentionally mid-plan, not first** — sequencing it once G1 and G4 exist gives
  the pipeline real code paths to lint/test/build against, rather than being set up against an
  incomplete tree.
