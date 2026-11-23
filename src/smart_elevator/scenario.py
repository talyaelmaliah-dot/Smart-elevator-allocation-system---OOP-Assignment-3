import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import ElevatorSpec, GeneratedTraffic, Scenario, TrafficProfile
from .domain import Building, Floor, PassengerRequest, Timing


def _validate(data: Any) -> None:
    schema = json.loads(
        files(__package__).joinpath("simulation-v1.schema.json").read_text(encoding="utf-8")
    )
    mode = data.get("traffic") if isinstance(data, dict) else None
    mode = mode.get("mode") if isinstance(mode, dict) else None
    if mode in ("generated", "explicit"):
        # Select the same schema branch by its discriminator for precise errors.
        schema["properties"]["traffic"] = {"$ref": f"#/$defs/{mode}Traffic"}

    error = next(Draft202012Validator(schema).iter_errors(data), None)
    if error is not None:
        raise ValueError(f"{error.json_path}: {error.message}")

    # JSON Schema accepts integral floats. The core uses Python integers.
    def check_integers(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                check_integers(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check_integers(child, f"{path}[{index}]")
        elif isinstance(value, float):
            raise ValueError(f"{path}: expected an integer")

    check_integers(data, "$")


def _ordered(
    requests: tuple[PassengerRequest, ...],
) -> tuple[PassengerRequest, ...]:
    return tuple(sorted(requests, key=lambda request: (request.requested_at_ms, request.id)))


def _parse(data: Any) -> Scenario:
    _validate(data)
    building_data = data["building"]
    floor_count = building_data["floor_count"]
    lobby = building_data["lobby_floor"]

    def check_floor(value: int, path: str) -> None:
        if value >= floor_count:
            raise ValueError(f"{path}: floor must be below {floor_count}")

    check_floor(lobby, "$.building.lobby_floor")
    building = Building(tuple(Floor(index) for index in range(floor_count)), lobby)

    elevator_ids: set[str] = set()
    elevators = []
    for index, item in enumerate(building_data["elevators"]):
        path = f"$.building.elevators[{index}]"
        elevator = ElevatorSpec(**item)
        check_floor(elevator.start_floor, f"{path}.start_floor")
        if elevator.id in elevator_ids:
            raise ValueError(f"{path}.id: duplicate elevator ID {elevator.id!r}")
        elevator_ids.add(elevator.id)
        elevators.append(elevator)

    traffic_data = data["traffic"]
    traffic: GeneratedTraffic | tuple[PassengerRequest, ...]
    if traffic_data["mode"] == "generated":
        traffic = GeneratedTraffic(
            TrafficProfile(traffic_data["profile"]),
            traffic_data["seed"],
            traffic_data["request_count"],
            traffic_data["duration_ms"],
        )
    else:
        request_ids: set[str] = set()
        requests = []
        for index, item in enumerate(traffic_data["requests"]):
            path = f"$.traffic.requests[{index}]"
            request = PassengerRequest(**item)
            check_floor(request.origin, f"{path}.origin")
            check_floor(request.destination, f"{path}.destination")
            if request.origin == request.destination:
                raise ValueError(f"{path}.destination: must differ from origin")
            if request.id in request_ids:
                raise ValueError(f"{path}.id: duplicate request ID {request.id!r}")
            request_ids.add(request.id)
            requests.append(request)
        traffic = _ordered(tuple(requests))

    return Scenario(building, Timing(**data["timing"]), tuple(elevators), traffic)


def load_scenario(path: Path) -> Scenario:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"$: {error}") from error
    return _parse(data)


def save_explicit_scenario(
    path: Path, scenario: Scenario, requests: tuple[PassengerRequest, ...]
) -> None:
    data = {
        "schema_version": 1,
        "building": {
            "floor_count": len(scenario.building.floors),
            "lobby_floor": scenario.building.lobby_floor,
            "elevators": [asdict(elevator) for elevator in scenario.elevators],
        },
        "timing": asdict(scenario.timing),
        "traffic": {
            "mode": "explicit",
            "requests": [asdict(request) for request in _ordered(requests)],
        },
    }
    _parse(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
