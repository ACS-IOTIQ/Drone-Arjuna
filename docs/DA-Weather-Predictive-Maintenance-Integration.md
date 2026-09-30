# DroneArjuna Weather POC — Documentation & Integration Plan

**Status:** POC review — not yet integrated
**Author context:** ACS Technologies Limited
**Date:** 2026-09-24
**Target integration:** DroneArjuna main Ground Control System backend

---

## 1. Motivation: why this POC was built

In DroneArjuna, a drone flying from one place to another is tracked live on the map for the duration of its journey. As it moves, it passes through a series of different locations, each of which can have its own local weather at that moment — wind, rain, humidity, temperature, and so on can all vary meaningfully along a single route rather than staying constant for the whole flight.

The idea behind the Weather POC is to fetch live weather data for the drone's position as it moves, rather than relying on a single weather check made before takeoff. Wind, rain, and humidity along the tracked route are the specific conditions of interest, because they are the conditions most directly linked to component stress and wear over time — motors working harder against wind, moisture affecting electronics and batteries, and so on. Capturing what a drone actually flew through, point by point along its tracked path, is what makes it possible to later connect flight history to predictive maintenance, rather than only ever knowing that a drone flew for a certain number of hours without knowing what it flew through.

The POC was developed to prove out this live weather-fetching and safety-assessment approach in isolation, before wiring it into DroneArjuna's map tracking.

## 2. What the Weather POC is

The Weather POC is a standalone proof of concept that answers one question for a given Indian location: can a drone fly right now, based on live weather?

It works through a simple pipeline. First, it converts a place name into coordinates using an open mapping service. It then fetches current weather conditions from a primary weather provider, with a backup provider used if the first one fails. To improve confidence in the reading, it cross-checks the primary data against up to two additional independent weather sources, producing a data-confidence score. Fixed, rule-based safety thresholds are then applied to reach one of three outcomes — Safe, Caution, or Blocked — along with a 0–100 safety score. Separately, it checks whether the location is near a known military installation; this is informational only and does not by itself block a flight. Finally, a small local language model writes a plain-English explanation of the result. The safety decision itself always comes from the rule engine, never from the language model — the model only narrates it.

The POC is reachable both as a command-line tool and as a small web application with an interactive map, and it already supports checking multiple points at once — a natural fit for sampling weather along a tracked flight path rather than only at a single location.

## 3. Approach and dependencies

The POC is built entirely in Python, using a lightweight web framework for its API and browser interface. It relies on a handful of external weather and mapping services accessed over plain HTTP calls, plus a small local database for caching one of the government weather sources. It does not require a login or any user accounts, and it does not persist results beyond its cache. It also depends on a locally running small language model to generate its narrative explanations.

## 4. Core logic worth carrying forward

**Safety thresholds.** The rule engine treats a flight as unsafe (blocked) once wind speed, rainfall rate, visibility, or temperature cross fixed limits, or if the reported condition is a severe weather event such as a thunderstorm or tornado. It treats a flight as caution-worthy (warned, not blocked) when gusts, humidity, or cloud cover cross separate, lower thresholds — humidity because of its effect on batteries and electronics, and heavy cloud cover because of possible GPS signal degradation. Each violation and warning subtracts from a 100-point starting score, giving an overall 0–100 safety rating alongside the Safe/Caution/Blocked label.

**Cross-source confidence.** When more than one weather source is available for a location, the POC compares them against tolerance bands for temperature, wind, humidity, rainfall, and pressure, and produces a High/Medium/Low confidence rating. At present this confidence rating is shown for information only — it does not change or override the safety decision above.

**Multiple weather sources.** The POC deliberately does not rely on a single weather provider. Its primary source is a major commercial weather API with a free secondary provider as automatic fallback, and it draws on two additional data sources — a citizen weather-station network and a national government weather agency's station feed — purely for the cross-check step described above. This diversity of sources is a useful property to preserve during integration, since it makes the safety decision less sensitive to any single provider's gaps or outages.

## 5. Purpose of integrating into DroneArjuna: predictive maintenance

The main DroneArjuna Ground Control System backend currently has no weather awareness at all — nothing in it fetches or evaluates weather conditions. It does have a live, threshold-based health monitor for each drone that watches things like battery level, signal strength, GPS satellite count, and processor load, but this is purely reactive: it reports problems as they happen rather than anticipating them. The system also tracks each drone's cumulative flight hours and a maintenance status flag, but there is no maintenance schedule, wear model, or degradation forecasting built on top of that data today.

The integration goal is to feed live weather data — wind, rain, and humidity in particular — into DroneArjuna's existing map tracking of a drone's journey from one place to another, so that:

- As a drone moves and is tracked on the map, the weather conditions it is actually passing through at each point along its route are captured, not just a single before-takeoff check. This turns a flight from a single flight-hours number into a record of what the drone actually flew through.
- Component wear and maintenance scheduling can then factor in the *actual conditions a drone has flown in*, not just raw flight-hour counts. A drone that has spent a disproportionate share of its flight hours in high humidity or high wind is reasonably expected to need earlier attention to its battery, motors, or gimbal than one that has flown mostly in mild conditions.
- Missions can be screened against live or forecast weather at planning time, before a drone ever leaves the ground.
- The existing reactive health monitor can be complemented by a predictive layer that flags, ahead of time, that a given drone is approaching a maintenance threshold sooner than its flight-hour total alone would suggest, because of the conditions it has actually been exposed to along its tracked routes.

## 6. Proposed integration approach

The recommended approach is to introduce weather awareness as a new module in DroneArjuna, built in the same self-contained style as its existing five modules, rather than scattering weather logic across the existing ones. This new module would be responsible for periodically fetching weather for each active mission location and each drone's home base, applying the same safety-threshold logic proven in the POC, and exposing the results through the backend's API in the same way the existing modules do.

The weather readings themselves would be stored over time, associated with a location and a timestamp, so that a history of conditions builds up rather than only the latest reading being available. Each drone's cumulative exposure to adverse conditions — for example, total hours flown under high humidity or high wind — would be derived by combining this weather history with the drone's existing flight-history data, and used as an input to a new predictive-maintenance scoring capability. This scoring capability does not exist in the POC and would need to be designed fresh for DroneArjuna.

Access to the new weather features should follow the same role-based permission model already used throughout DroneArjuna, so that, for example, any authenticated user can view current conditions while only mission-authorized roles can act on them. Weather-related alerts and predicted-maintenance notices should flow through the same internal event/notification mechanism the backend already uses for other alerts, so they show up consistently alongside existing system notifications. On the frontend, weather information should appear where operators already plan and monitor flights, and maintenance-risk indicators should appear where they already review fleet status.

Configuration such as which weather provider to use, credentials for it, and how often to poll should be handled the same way all other environment-specific settings in DroneArjuna are handled today, rather than being hardcoded — this also resolves the one real weakness of the POC, which currently embeds its provider credential directly rather than reading it from configuration.

## 7. Migration checklist (POC → production capability)

- [ ] Reimplement the safety-threshold and cross-check logic natively in the DroneArjuna backend rather than reusing POC code as-is; the narrative-explanation step is not needed server-side, since the frontend can present the structured result directly.
- [ ] Move all provider credentials and configurable thresholds into DroneArjuna's standard configuration system rather than hardcoding them, correcting the one real gap in the POC.
- [ ] Replace the POC's lightweight local cache with DroneArjuna's existing time-series and caching infrastructure.
- [ ] Decide whether the cross-source confidence rating should be allowed to influence the safety decision (for example, downgrading a "Safe" result to "Caution" when confidence is low) — the POC currently keeps this purely informational, and DroneArjuna should make a deliberate choice either way.
- [ ] Design and build the predictive-maintenance scoring capability itself — this is new work, not present in the POC, that combines weather exposure history with existing flight-hour and telemetry data.
- [ ] Add automated test coverage for the new weather and maintenance-prediction logic, following the testing conventions already used elsewhere in the backend.
- [ ] Update project documentation and status tracking once the module is merged.

## 8. Summary

The Weather POC proves out a sound, multi-source, rule-based approach to flight-safety weather assessment, and it is a reasonable starting point for design rather than a system to bolt on unmodified. The real value for DroneArjuna is not the POC's code itself but the *pattern* it demonstrates — combining several weather sources with fixed safety thresholds to produce a trustworthy, explainable decision — applied to a genuinely new capability that does not exist yet anywhere in the project: using accumulated environmental exposure, alongside flight hours, to predict maintenance needs before they become failures.
