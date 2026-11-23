import json
from pathlib import Path

from smart_elevator.contracts import (
    AllocationContext,
    AllocationDecision,
    GeneratedTraffic,
    Stop,
)
from smart_elevator.domain import PassengerRequest
from smart_elevator.generator import RequestGenerator
from smart_elevator.scenario import load_scenario, save_explicit_scenario
from smart_elevator.simulator import Simulator


class AppendAllocator:
    def allocate(
        self, request: PassengerRequest, context: AllocationContext
    ) -> AllocationDecision:
        car = context.elevators[0]
        return AllocationDecision(
            car.id,
            car.pending_stops
            + (
                Stop(request.origin, (), (request.id,)),
                Stop(request.destination, (request.id,), ()),
            ),
        )


def test_generated_workload_replays_from_explicit_scenario(tmp_path: Path) -> None:
    path = tmp_path / "generated.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "building": {
                    "floor_count": 3,
                    "lobby_floor": 0,
                    "elevators": [{"id": "E", "start_floor": 0, "capacity": 1}],
                },
                "timing": {"travel_ms_per_floor": 10, "door_dwell_ms": 5},
                "traffic": {
                    "mode": "generated",
                    "profile": "mixed",
                    "seed": 42,
                    "request_count": 8,
                    "duration_ms": 4,
                },
            }
        ),
        encoding="utf-8",
    )
    scenario = load_scenario(path)
    assert isinstance(scenario.traffic, GeneratedTraffic)
    requests = RequestGenerator().generate(scenario.building, scenario.traffic)
    generated = Simulator(scenario, requests, AppendAllocator()).run()

    explicit_path = tmp_path / "explicit.json"
    save_explicit_scenario(explicit_path, scenario, requests)
    explicit_scenario = load_scenario(explicit_path)
    explicit_requests = explicit_scenario.traffic
    assert isinstance(explicit_requests, tuple)
    assert explicit_requests == requests
    replay = Simulator(explicit_scenario, explicit_requests, AppendAllocator()).run()

    assert replay == generated
    assert replay.completed_count == 8
    assert replay.snapshot.now_ms > scenario.traffic.duration_ms
    assert replay.snapshot.finished
    assert tuple(passenger.request for passenger in replay.snapshot.passengers) == requests
