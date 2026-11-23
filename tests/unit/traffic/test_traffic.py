import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from smart_elevator.contracts import GeneratedTraffic, Stop, TrafficProfile
from smart_elevator.domain import Building, Elevator, Floor, PassengerRequest
from smart_elevator.generator import RequestGenerator
from smart_elevator.scenario import load_scenario, save_explicit_scenario


EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def test_building_and_elevator_snapshot() -> None:
    building = Building((Floor(0), Floor(1)), 0)
    assert building.floor(1) is building.floors[1]
    for invalid in (-1, 2, True):
        with pytest.raises(ValueError):
            building.floor(invalid)
    with pytest.raises(ValueError, match="contiguous"):
        Building((Floor(0), Floor(2)), 0)

    car = Elevator("E1", 0, 2)
    assert car.snapshot().available_at_ms == 0
    stop = Stop(1, ("Z", "A"), ())
    car.onboard_ids.update(("Z", "A"))
    car.active_stop = stop
    car.arrival_at_ms = 10
    car.available_at_ms = 15
    car.pending_stops = (Stop(1, (), ("B",)),)
    snapshot = car.snapshot()
    car.onboard_ids.clear()
    car.pending_stops = ()
    assert snapshot.onboard_ids == ("A", "Z")
    assert snapshot.active_stop.dropoff_ids == ("A", "Z")
    assert snapshot.arrival_at_ms == 10
    assert snapshot.available_at_ms == 15
    assert snapshot.pending_stops == (Stop(1, (), ("B",)),)
    with pytest.raises(FrozenInstanceError):
        snapshot.last_floor = 1


@pytest.mark.parametrize("profile", list(TrafficProfile))
def test_profiles_and_seeded_replay(profile: TrafficProfile) -> None:
    building = Building(tuple(Floor(index) for index in range(4)), 2)
    spec = GeneratedTraffic(profile, 42, 400, 5)
    generator = RequestGenerator()
    requests = generator.generate(building, spec)
    generator.generate(building, replace(spec, seed=9))
    assert requests == generator.generate(building, spec)
    assert requests != generator.generate(building, replace(spec, seed=9))

    assert len(requests) == spec.request_count
    assert {r.id for r in requests} == {f"R{i}" for i in range(1, 401)}
    keys = [(r.requested_at_ms, r.id) for r in requests]
    assert keys == sorted(keys)
    assert all(0 <= r.requested_at_ms < spec.duration_ms for r in requests)
    pairs = {(r.origin, r.destination) for r in requests}
    all_pairs = {(i, j) for i in range(4) for j in range(4) if i != j}
    if profile is TrafficProfile.MORNING_RUSH:
        assert pairs == {pair for pair in all_pairs if pair[0] == 2}
    elif profile is TrafficProfile.EVENING_RUSH:
        assert pairs == {pair for pair in all_pairs if pair[1] == 2}
    else:
        assert pairs == all_pairs


@pytest.mark.parametrize(
    ("field", "value"),
    [("seed", -1), ("request_count", -1), ("duration_ms", 0), ("seed", True)],
)
def test_invalid_generator_spec(field: str, value: int) -> None:
    building = Building((Floor(0), Floor(1)), 0)
    spec = GeneratedTraffic(TrafficProfile.RANDOM, 0, 0, 1)
    assert RequestGenerator().generate(building, spec) == ()
    with pytest.raises(ValueError, match=field):
        RequestGenerator().generate(building, replace(spec, **{field: value}))


def test_generated_workload_round_trip(tmp_path: Path) -> None:
    scenario = load_scenario(EXAMPLES / "generated.json")
    assert isinstance(scenario.traffic, GeneratedTraffic)
    requests = RequestGenerator().generate(scenario.building, scenario.traffic)

    path = tmp_path / "explicit.json"
    save_explicit_scenario(path, scenario, tuple(reversed(requests)))
    assert load_scenario(path) == replace(scenario, traffic=requests)
    assert json.loads(path.read_text())["traffic"]["mode"] == "explicit"

    canonical = tmp_path / "canonical.json"
    save_explicit_scenario(canonical, scenario, requests)
    assert canonical.read_bytes() == path.read_bytes()


def test_explicit_workload_sorted_by_timestamp_and_id(tmp_path: Path) -> None:
    data = json.loads((EXAMPLES / "explicit.json").read_text())
    data["traffic"]["requests"].extend(
        [
            {"id": "R0", "requested_at_ms": 1, "origin": 3, "destination": 0},
            {"id": "A", "requested_at_ms": 0, "origin": 1, "destination": 2},
        ]
    )
    path = tmp_path / "unsorted.json"
    path.write_text(json.dumps(data))
    assert load_scenario(path).traffic == (
        PassengerRequest("A", 0, 1, 2),
        PassengerRequest("R1", 0, 0, 3),
        PassengerRequest("R0", 1, 3, 0),
    )


@pytest.mark.parametrize(
    ("example", "keys", "value", "expected_path"),
    [
        ("explicit", ("schema_version",), 2, "$.schema_version"),
        ("explicit", ("schema_version",), 1.0, "$.schema_version"),
        ("explicit", ("building", "floor_count"), 1, "$.building.floor_count"),
        ("explicit", ("building", "lobby_floor"), 4, "$.building.lobby_floor"),
        (
            "explicit", ("building", "elevators", 0, "start_floor"), 4,
            "$.building.elevators[0].start_floor",
        ),
        (
            "explicit", ("building", "elevators", 0, "capacity"), 0,
            "$.building.elevators[0].capacity",
        ),
        ("explicit", ("timing", "door_dwell_ms"), 0, "$.timing.door_dwell_ms"),
        (
            "explicit", ("traffic", "requests", 0, "requested_at_ms"), 2.0,
            "$.traffic.requests[0].requested_at_ms",
        ),
        (
            "explicit", ("traffic", "requests", 0, "origin"), 4,
            "$.traffic.requests[0].origin",
        ),
        (
            "explicit", ("traffic", "requests", 0, "destination"), 0,
            "$.traffic.requests[0].destination",
        ),
        ("generated", ("traffic", "duration_ms"), 0, "$.traffic.duration_ms"),
        ("generated", ("traffic", "profile"), "unknown", "$.traffic.profile"),
        ("generated", ("traffic", "requests"), [], "$.traffic"),
    ],
)
def test_invalid_field_path(
    tmp_path: Path,
    example: str,
    keys: tuple[str | int, ...],
    value: object,
    expected_path: str,
) -> None:
    data = json.loads((EXAMPLES / f"{example}.json").read_text())
    target = data
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError) as error:
        load_scenario(path)
    assert str(error.value).startswith(f"{expected_path}:")


@pytest.mark.parametrize(
    ("keys", "expected_path"),
    [
        (("building", "elevators"), "$.building.elevators[1].id"),
        (("traffic", "requests"), "$.traffic.requests[1].id"),
    ],
)
def test_duplicate_ids(
    tmp_path: Path, keys: tuple[str, str], expected_path: str
) -> None:
    data = json.loads((EXAMPLES / "explicit.json").read_text())
    items = data[keys[0]][keys[1]]
    items.append(items[0])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(data))

    with pytest.raises(ValueError) as error:
        load_scenario(path)
    assert str(error.value).startswith(f"{expected_path}:")


def test_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text("{")
    with pytest.raises(ValueError, match=r"^\$:"):
        load_scenario(path)
