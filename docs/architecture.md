# Smart Elevator System architecture

## Scope and objective

Each request represents one passenger whose origin and destination are known at submission. Minimize the sum of `arrived_at_ms - requested_at_ms` across all requests. Record waiting time as pickup minus request time and riding time as arrival minus pickup, and report completed count, total and mean journey time, mean wait, and maximum journey time. Use zero for empty aggregates. Expose those same aggregates for completed passengers in the GUI while a run is in progress. Compare policies on the same materialized workload and configuration. The model assumes uniform floor spacing, instantaneous boarding and alighting, fixed door dwell, and no failures or priority passengers.

## Planned structure

```text
src/smart_elevator/
  __init__.py
  domain.py         Building, Floor, Elevator, PassengerRequest, Timing
  contracts.py      Read models, route plans, and protocols
  scenario.py       JSON validation and scenario loading/export
  generator.py      Seeded traffic profiles
  simulator.py      Event queue, dispatch, and passenger lifecycle
  allocation/      Baseline, route projection, and insertion allocator
  gui/             Tkinter views and controller
  __main__.py       Application composition and CLI
schemas/           Versioned JSON Schema
examples/          Generated and explicit scenario fixtures
tests/
  unit/            Component tests
  integration/     Real-component scenario tests
docs/
pyproject.toml
```

## Domain and public interfaces

Floor indices are contiguous from zero through `floor_count - 1`. IDs are case-sensitive strings ordered lexicographically. All timestamps and durations are integer milliseconds.

| Type | State and responsibility | Public API |
| --- | --- | --- |
| `Floor` | Immutable floor index | `Floor(index: int)` |
| `Building` | Immutable ordered tuple of floors and lobby index | `Building(floors: tuple[Floor, ...], lobby_floor: int)`, `floor(index: int) -> Floor` (raises `ValueError` for invalid index) |
| `PassengerRequest` | Immutable identity, arrival time, and endpoints | `PassengerRequest(id: str, requested_at_ms: int, origin: int, destination: int)` |
| `Timing` | Immutable travel and dwell settings | `Timing(travel_ms_per_floor: int, door_dwell_ms: int)` |
| `Elevator` | Simulator-owned identity, capacity, position, active movement or dwell, route, and onboard IDs | `Elevator(id: str, start_floor: int, capacity: int)`, `snapshot() -> ElevatorSnapshot`; the simulator owns all transitions |
| `RequestGenerator` | Materializes seeded traffic for a building | `generate(building: Building, spec: GeneratedTraffic) -> tuple[PassengerRequest, ...]` |
| `Simulator` | Owns simulation clock, queue, fleet, and passenger lifecycle | `Simulator(scenario: Scenario, requests: tuple[PassengerRequest, ...], allocator: Allocator)`, `step() -> SimulationSnapshot`, `snapshot() -> SimulationSnapshot`, `run() -> SimulationResult` |
| `Allocator` | Replaceable, side-effect-free policy | `allocate(request: PassengerRequest, context: AllocationContext) -> AllocationDecision \| None` |

`contracts.py` owns these shared immutable records and the `Allocator` protocol:

- `GeneratedTraffic(profile: TrafficProfile, seed: int, request_count: int, duration_ms: int)`. Use a string enum for the four schema profiles.
- `ElevatorSpec(id: str, start_floor: int, capacity: int)`; `Scenario(building: Building, timing: Timing, elevators: tuple[ElevatorSpec, ...], traffic: GeneratedTraffic | tuple[PassengerRequest, ...])`.
- `Stop(floor: int, dropoff_ids: tuple[str, ...], pickup_ids: tuple[str, ...])`. Adjacent stops at the same floor are allowed and served as separate door cycles. IDs within each action are sorted.
- `ElevatorSnapshot` carries `id: str`, `capacity: int`, `last_floor: int`, `onboard_ids: tuple[str, ...]`, `active_stop: Stop | None`, `arrival_at_ms: int | None`, `available_at_ms: int`, and `pending_stops: tuple[Stop, ...]`. A moving car exposes its committed stop, its arrival time, and the time after that stop's dwell. Otherwise the active stop and arrival time are absent, and availability is the dwell end or zero for an idle car.
- `AllocationContext(now_ms: int, timing: Timing, elevators: tuple[ElevatorSnapshot, ...], active_requests: tuple[PassengerRequest, ...])`. Fleet is sorted by ID and active requests contain all submitted, unfinished passengers, including the incoming request.
- `AllocationDecision(elevator_id: str, pending_stops: tuple[Stop, ...])` replaces the selected car's pending route. A decision preserves the prior pending stops as an ordered subsequence and inserts exactly one pickup stop and one later drop-off stop for the new passenger. An invalid decision raises `ValueError` before route mutation. `None` defers the request.
- `PassengerProgress(request: PassengerRequest, elevator_id: str | None, picked_up_at_ms: int | None, arrived_at_ms: int | None)`. `SimulationSnapshot(now_ms: int, elevators: tuple[ElevatorSnapshot, ...], passengers: tuple[PassengerProgress, ...], finished: bool)` contains all submitted passengers ordered by request time and ID.
- `SimulationResult` carries the final snapshot, `completed_count: int`, `total_journey_ms: int`, `mean_journey_ms: float`, `mean_wait_ms: float`, and `max_journey_ms: int`.

Use postponed annotations and type-checking-only imports where domain signatures refer to contract types. Runtime dependencies flow from adapters and implementations toward domain and contracts. The application wires all concrete dependencies.

## JSON and traffic generation

[The v1 JSON Schema](../schemas/simulation-v1.schema.json) defines a scenario envelope with exactly one traffic source. Example with a materialized request list:

```json
{
  "schema_version": 1,
  "building": {
    "floor_count": 4,
    "lobby_floor": 0,
    "elevators": [{"id": "E1", "start_floor": 0, "capacity": 2}]
  },
  "timing": {"travel_ms_per_floor": 1000, "door_dwell_ms": 500},
  "traffic": {
    "mode": "explicit",
    "requests": [{"id": "R1", "requested_at_ms": 0, "origin": 0, "destination": 3}]
  }
}
```

Generated traffic uses the same envelope with `"traffic": {"mode": "generated", "profile": "morning_rush", "seed": 42, "request_count": 20, "duration_ms": 60000}`.

`load_scenario(path: Path) -> Scenario` validates Draft 2020-12 structure and then checks floor bounds, distinct request endpoints, and unique elevator and request IDs. Report invalid data as `ValueError` with its field path. Sort explicit requests by `(requested_at_ms, id)`. `save_explicit_scenario(path: Path, scenario: Scenario, requests: tuple[PassengerRequest, ...]) -> None` writes the full scenario envelope with canonical explicit traffic. Package the checked-in schema so loading works from an installed distribution.

Generation uses a fresh `random.Random(seed)` per invocation. For each synthetic passenger, sample a timestamp uniformly from `[0, duration_ms)`. Random traffic samples uniformly from all ordered distinct floor pairs. Morning rush draws from lobby to a uniformly chosen non-lobby floor, and evening rush reverses that direction. Mixed samples the three profiles with equal probability per request. Generate stable IDs `R1`, `R2`, and so on in draw order, then return requests sorted by `(requested_at_ms, id)`. Exactly `request_count` requests are returned. Replay across environments uses the exported explicit workload.

## Discrete-event semantics

The caller materializes one request tuple from either traffic source and supplies it to the simulator. The simulator validates the supplied tuple against the building and initializes request-submission events. Its event queue uses time, event kind, and a monotonic insertion sequence. At each timestamp:

1. Process car arrivals and dwell completions before submissions. At a stop, alight before boarding, enforce capacity, and record destination arrival at the start of service. Equal-kind car events use elevator ID order.
2. Submit all new requests in ID order. Try unassigned requests by request time and ID. Apply validated decisions immediately so later calls see earlier assignments. Retry deferred requests on later event timestamps.
3. Start the next stop for each ready car in ID order. The committed stop is locked. Travel takes floor distance times the configured travel time. Serve a same-floor stop immediately, then schedule dwell completion. If immediate service changed passenger state, repeat dispatch and start newly ready cars at the same timestamp until there is no further immediate service. Each car can serve at most one stop at that timestamp because dwell is positive.

The lifecycle is waiting, assigned, onboard, then arrived. Only the simulator mutates that state. At completion, all requests have arrived and the event queue is drained. An exhausted queue with unfinished requests raises `RuntimeError`, including when a policy defers despite an idle fleet and no future events. `step()` processes one full timestamp and returns the final snapshot unchanged on subsequent calls after completion. `run()` repeatedly calls `step()` and returns final metrics; the generation window does not limit service time.

## Allocation strategy

Baseline appends pickup and drop-off to the car with the shortest projected time to the origin, resolving equal times by elevator ID. Both policies simulate the locked stop, remaining dwell, and pending stops in order. Baseline evaluates its appended route for capacity and skips infeasible candidates.

The optimization policy enumerates all positions for the two new stops in every car's pending route. Project from the committed stop and its available time if moving, or from the last floor at `max(now_ms, available_at_ms)` otherwise. Apply drop-offs before pickups and charge a full dwell per stop. Reject candidates violating capacity or pickup-before-drop-off. Evaluate the locked stop at its recorded arrival time, including its passenger actions. Score each candidate as the new passenger's projected journey time plus the projected arrival-time changes for existing passengers assigned to that car, relative to its original route. Other cars contribute zero change. Resolve ties by elevator ID, pickup insertion index, then drop-off insertion index in the final pending list. This searches the permitted insertion neighborhood for the current request. Future arrivals may change which sequence would have been best in hindsight.

## GUI and ESP32 boundary

The planned Tkinter GUI loads a scenario, draws building floors and elevator state, and shows passengers and journey metrics. Its controller exposes load, play, pause, step, and reset actions. Use Tk's timer to pace calls to `step()`; simulated timestamps come from snapshots. Reset constructs a new simulator from the same materialized workload. Smoke-test by loading the example, stepping through pickup, pausing and resuming, checking final metrics, and resetting to time zero.

A future host adapter and ESP32 client will share a transport-neutral, versioned message envelope with `version`, `type`, `message_id`, and `payload`. Plan for `submit_request` (origin and destination), `ack` (correlated message ID, acceptance or validation error), and `snapshot` (read-only simulated time and car state). The simulator thread serializes accepted commands at event boundaries and stamps requests with current simulated time. The adapter deduplicates incoming message IDs per connection session and returns the same acknowledgment on retry. WiFi can carry JSON over WebSocket; BLE can use GATT writes and notifications with framing for the negotiated packet size. Future work includes defining that wire schema, session and reconnect behavior, command ingestion, and emulator and hardware tests.

## Four independent development branches

Branch from the same reviewed planning commit. The integration lead owns root documentation, `docs/`, and `schemas/`. All listed implementation paths have one owning branch.

| Branch | Owned paths | Deliverables and acceptance |
| --- | --- | --- |
| `feat/domain-traffic` | `pyproject.toml`, package `__init__.py`, `domain.py`, `contracts.py`, `scenario.py`, `generator.py`, `examples/`, `tests/unit/traffic/` | Implement types, packaging, validation, generation, explicit export, and tests for all profiles, deterministic replay, round-trip, and invalid inputs. Publish shared types first for pickup by other branches. |
| `feat/simulator` | `simulator.py`, `tests/unit/simulator/`, `tests/integration/test_simulator_pipeline.py` | Implement event loop, snapshots, lifecycle, and metrics. Use a fake allocator for tie order, same-floor service, capacity and failure cases. Integrate generated and explicit traffic with a deterministic fake policy. |
| `feat/allocation` | `allocation/`, `tests/unit/allocation/`, `tests/integration/test_allocation_comparison.py` | Implement route projection, baseline, and insertion allocator. Test locked stops, capacity, score and ties using fabricated snapshots. Run both policies on identical scenarios, verify exact metrics on a hand-checkable case and an improvement in a fixture where appending delays an otherwise feasible pickup. |
| `feat/gui` | `gui/`, `__main__.py`, `tests/unit/gui/`, `tests/integration/test_application.py` | Wire loading and policy selection, implement the Tkinter interface and controller, and test controls with a fake simulator. Add a headless application integration test and run the GUI smoke test. |

Paths such as `simulator.py` and `allocation/` in the ownership table are relative to `src/smart_elevator/`. The domain branch owns any packaging entry point metadata and the pytest dev extra. Use `python -m smart_elevator <scenario.json>` for the GUI and support `--headless` and `--allocator {insertion,baseline}` through the same entry point. Default to insertion.

The lead merges the contract foundation first, then simulator, allocation, and GUI. Begin component tests against the documented signatures and use local fakes until the foundation and earlier dependencies land. Keep cross-component tests in the assigned files and avoid a shared test fixture module. Before release, run the full suite, verify a saved workload replays to identical metrics, and record baseline and optimized results for all four traffic profiles with fixed seeds and identical fleet settings.
