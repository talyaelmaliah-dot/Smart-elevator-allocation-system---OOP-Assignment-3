from __future__ import annotations

from ..contracts import AllocationContext, AllocationDecision, Stop
from ..domain import PassengerRequest
from ._projection import project_route


class InsertionAllocator:
    """Choose the feasible insertion with the smallest journey-time cost."""

    def allocate(
        self, request: PassengerRequest, context: AllocationContext
    ) -> AllocationDecision | None:
        pickup = Stop(request.origin, (), (request.id,))
        dropoff = Stop(request.destination, (request.id,), ())
        best_key: tuple[int, str, int, int] | None = None
        decision = None

        for elevator in context.elevators:
            pending = elevator.pending_stops
            original = project_route(elevator, context, pending)
            if original is None:
                continue

            for pickup_index in range(len(pending) + 1):
                with_pickup = (*pending[:pickup_index], pickup, *pending[pickup_index:])
                for dropoff_index in range(pickup_index + 1, len(with_pickup) + 1):
                    stops = (
                        *with_pickup[:dropoff_index],
                        dropoff,
                        *with_pickup[dropoff_index:],
                    )
                    projection = project_route(elevator, context, stops)
                    if projection is None:
                        continue

                    arrivals = projection.arrival_times
                    existing_delay = sum(
                        arrivals[passenger_id] - original_arrival
                        for passenger_id, original_arrival in original.arrival_times.items()
                    )
                    score = arrivals[request.id] - request.requested_at_ms + existing_delay
                    key = (score, elevator.id, pickup_index, dropoff_index)
                    if best_key is None or key < best_key:
                        best_key = key
                        decision = AllocationDecision(elevator.id, stops)

        return decision
