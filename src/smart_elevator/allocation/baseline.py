from __future__ import annotations

from ..contracts import AllocationContext, AllocationDecision, Stop
from ..domain import PassengerRequest
from ._projection import project_route


class BaselineAllocator:
    """Append the trip to the car that can reach the pickup first."""

    def allocate(
        self, request: PassengerRequest, context: AllocationContext
    ) -> AllocationDecision | None:
        pickup = Stop(request.origin, (), (request.id,))
        dropoff = Stop(request.destination, (request.id,), ())
        best_key: tuple[int, str] | None = None
        decision = None

        for elevator in context.elevators:
            stops = (*elevator.pending_stops, pickup, dropoff)
            projection = project_route(elevator, context, stops)
            if projection is None:
                continue

            key = (projection.pickup_times[request.id], elevator.id)
            if best_key is None or key < best_key:
                best_key = key
                decision = AllocationDecision(elevator.id, stops)

        return decision
