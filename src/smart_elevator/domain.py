from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import ElevatorSnapshot, Stop


@dataclass(frozen=True)
class Floor:
    index: int


@dataclass(frozen=True)
class Building:
    floors: tuple[Floor, ...]
    lobby_floor: int

    def __post_init__(self) -> None:
        if any(floor.index != index for index, floor in enumerate(self.floors)):
            raise ValueError("floors must be contiguous from zero")
        self.floor(self.lobby_floor)

    def floor(self, index: int) -> Floor:
        if type(index) is not int or not 0 <= index < len(self.floors):
            raise ValueError(f"invalid floor index: {index!r}")
        return self.floors[index]


@dataclass(frozen=True)
class PassengerRequest:
    id: str
    requested_at_ms: int
    origin: int
    destination: int


@dataclass(frozen=True)
class Timing:
    travel_ms_per_floor: int
    door_dwell_ms: int


class Elevator:
    def __init__(self, id: str, start_floor: int, capacity: int) -> None:
        self.id = id
        self.capacity = capacity
        self.last_floor = start_floor
        self.onboard_ids: set[str] = set()
        self.active_stop: Stop | None = None
        self.arrival_at_ms: int | None = None
        self.available_at_ms = 0
        self.pending_stops: tuple[Stop, ...] = ()

    def snapshot(self) -> ElevatorSnapshot:
        from .contracts import ElevatorSnapshot

        return ElevatorSnapshot(
            id=self.id,
            capacity=self.capacity,
            last_floor=self.last_floor,
            onboard_ids=tuple(sorted(self.onboard_ids)),
            active_stop=self.active_stop,
            arrival_at_ms=self.arrival_at_ms,
            available_at_ms=self.available_at_ms,
            pending_stops=tuple(self.pending_stops),
        )
