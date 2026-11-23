from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .domain import Building, PassengerRequest, Timing


class TrafficProfile(StrEnum):
    RANDOM = "random"
    MORNING_RUSH = "morning_rush"
    EVENING_RUSH = "evening_rush"
    MIXED = "mixed"


@dataclass(frozen=True)
class GeneratedTraffic:
    profile: TrafficProfile
    seed: int
    request_count: int
    duration_ms: int


@dataclass(frozen=True)
class ElevatorSpec:
    id: str
    start_floor: int
    capacity: int


@dataclass(frozen=True)
class Scenario:
    building: Building
    timing: Timing
    elevators: tuple[ElevatorSpec, ...]
    traffic: GeneratedTraffic | tuple[PassengerRequest, ...]


@dataclass(frozen=True)
class Stop:
    floor: int
    dropoff_ids: tuple[str, ...]
    pickup_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dropoff_ids", tuple(sorted(self.dropoff_ids)))
        object.__setattr__(self, "pickup_ids", tuple(sorted(self.pickup_ids)))


@dataclass(frozen=True)
class ElevatorSnapshot:
    id: str
    capacity: int
    last_floor: int
    onboard_ids: tuple[str, ...]
    active_stop: Stop | None
    arrival_at_ms: int | None
    available_at_ms: int
    pending_stops: tuple[Stop, ...]


@dataclass(frozen=True)
class AllocationContext:
    now_ms: int
    timing: Timing
    elevators: tuple[ElevatorSnapshot, ...]
    active_requests: tuple[PassengerRequest, ...]


@dataclass(frozen=True)
class AllocationDecision:
    elevator_id: str
    pending_stops: tuple[Stop, ...]


class Allocator(Protocol):
    def allocate(
        self, request: PassengerRequest, context: AllocationContext
    ) -> AllocationDecision | None: ...


@dataclass(frozen=True)
class PassengerProgress:
    request: PassengerRequest
    elevator_id: str | None
    picked_up_at_ms: int | None
    arrived_at_ms: int | None


@dataclass(frozen=True)
class SimulationSnapshot:
    now_ms: int
    elevators: tuple[ElevatorSnapshot, ...]
    passengers: tuple[PassengerProgress, ...]
    finished: bool


@dataclass(frozen=True)
class SimulationResult:
    snapshot: SimulationSnapshot
    completed_count: int
    total_journey_ms: int
    mean_journey_ms: float
    mean_wait_ms: float
    max_journey_ms: int
