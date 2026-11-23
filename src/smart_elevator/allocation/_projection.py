from __future__ import annotations

from dataclasses import dataclass

from ..contracts import AllocationContext, ElevatorSnapshot, Stop


@dataclass
class RouteProjection:
    pickup_times: dict[str, int]
    arrival_times: dict[str, int]


def project_route(
    elevator: ElevatorSnapshot,
    context: AllocationContext,
    pending_stops: tuple[Stop, ...],
) -> RouteProjection | None:
    """Project service times without changing the elevator snapshot."""
    onboard = set(elevator.onboard_ids)
    pickups: dict[str, int] = {}
    arrivals: dict[str, int] = {}

    def serve(stop: Stop, service_ms: int) -> bool:
        for passenger_id in stop.dropoff_ids:
            if passenger_id not in onboard:
                return False
            onboard.remove(passenger_id)
            arrivals[passenger_id] = service_ms

        for passenger_id in stop.pickup_ids:
            if passenger_id in onboard or passenger_id in arrivals:
                return False
            onboard.add(passenger_id)
            pickups[passenger_id] = service_ms

        return len(onboard) <= elevator.capacity

    floor = elevator.last_floor
    ready_ms = max(context.now_ms, elevator.available_at_ms)
    if elevator.active_stop is not None:
        assert elevator.arrival_at_ms is not None
        if not serve(elevator.active_stop, elevator.arrival_at_ms):
            return None
        floor = elevator.active_stop.floor
        ready_ms = elevator.available_at_ms

    for stop in pending_stops:
        service_ms = ready_ms + abs(stop.floor - floor) * context.timing.travel_ms_per_floor
        if not serve(stop, service_ms):
            return None
        floor = stop.floor
        ready_ms = service_ms + context.timing.door_dwell_ms

    return RouteProjection(pickups, arrivals)
