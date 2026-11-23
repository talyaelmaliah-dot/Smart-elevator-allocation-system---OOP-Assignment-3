import pytest

from smart_elevator.allocation import BaselineAllocator, InsertionAllocator
from smart_elevator.allocation._projection import project_route
from smart_elevator.contracts import (
    AllocationContext,
    AllocationDecision,
    Allocator,
    ElevatorSnapshot,
    Stop,
)
from smart_elevator.domain import PassengerRequest, Timing


def test_projection_uses_locked_arrival_and_drops_off_before_pickup() -> None:
    elevator = ElevatorSnapshot(
        "A", 1, 0, ("first",), Stop(5, ("first",), ("second",)), 180, 190,
        (Stop(7, ("second",), ()),),
    )
    context = AllocationContext(150, Timing(100, 10), (elevator,), ())

    projection = project_route(elevator, context, elevator.pending_stops)

    assert projection is not None
    assert projection.pickup_times == {"second": 180}
    assert projection.arrival_times == {"first": 180, "second": 390}


@pytest.mark.parametrize("allocator", [BaselineAllocator(), InsertionAllocator()])
def test_full_car_can_pick_up_only_after_dropoff(allocator: Allocator) -> None:
    request = PassengerRequest("new", 0, 0, 1)
    old = PassengerRequest("old", 0, 0, 4)
    old_dropoff = Stop(4, (old.id,), ())
    elevator = ElevatorSnapshot("A", 1, 0, (old.id,), None, None, 0, (old_dropoff,))
    context = AllocationContext(0, Timing(100, 10), (elevator,), (old, request))

    assert allocator.allocate(request, context) == AllocationDecision(
        "A", (old_dropoff, Stop(0, (), (request.id,)), Stop(1, (request.id,), ()))
    )


@pytest.mark.parametrize("allocator", [BaselineAllocator(), InsertionAllocator()])
def test_locked_pickup_cannot_be_bypassed(allocator: Allocator) -> None:
    request = PassengerRequest("new", 5, 1, 2)
    old = PassengerRequest("old", 0, 1, 4)
    old_pickup = Stop(1, (), (old.id,))
    old_dropoff = Stop(4, (old.id,), ())
    elevator = ElevatorSnapshot("A", 1, 0, (), old_pickup, 100, 110, (old_dropoff,))
    context = AllocationContext(5, Timing(100, 10), (elevator,), (old, request))

    assert allocator.allocate(request, context) == AllocationDecision(
        "A", (old_dropoff, Stop(1, (), (request.id,)), Stop(2, (request.id,), ()))
    )
    assert elevator.active_stop == old_pickup
    assert elevator.pending_stops == (old_dropoff,)


def test_projection_rejects_dropoff_before_pickup() -> None:
    elevator = ElevatorSnapshot("A", 1, 0, (), None, None, 0, ())
    context = AllocationContext(0, Timing(100, 10), (elevator,), ())

    assert project_route(elevator, context, (Stop(1, ("new",), ()),)) is None


def test_insertion_score_includes_delay_to_existing_passenger() -> None:
    request = PassengerRequest("new", 0, 1, 0)
    old = PassengerRequest("old", 0, 0, 4)
    busy = ElevatorSnapshot("A", 2, 0, (old.id,), None, None, 0, (Stop(4, (old.id,), ()),))
    idle = ElevatorSnapshot("B", 2, 3, (), None, None, 0, ())
    context = AllocationContext(0, Timing(100, 10), (busy, idle), (old, request))

    # A can complete the new trip at 210 ms, but adds 220 ms to the old trip.
    # B completes the new trip at 310 ms with no effect on the old trip.
    assert InsertionAllocator().allocate(request, context) == AllocationDecision(
        "B", (Stop(1, (), (request.id,)), Stop(0, (request.id,), ()))
    )


@pytest.mark.parametrize("allocator", [BaselineAllocator(), InsertionAllocator()])
def test_elevator_tie_uses_lexicographic_id(allocator: Allocator) -> None:
    request = PassengerRequest("new", 0, 1, 3)
    first = ElevatorSnapshot("E10", 1, 0, (), None, None, 0, ())
    second = ElevatorSnapshot("E2", 1, 2, (), None, None, 0, ())
    context = AllocationContext(0, Timing(100, 10), (first, second), (request,))

    assert allocator.allocate(request, context) == AllocationDecision(
        "E10", (Stop(1, (), (request.id,)), Stop(3, (request.id,), ()))
    )


def test_insertion_tie_uses_pickup_then_dropoff_index() -> None:
    request = PassengerRequest("new", 0, 0, 2)
    old = PassengerRequest("old", 0, 0, 2)
    old_pickup = Stop(0, (), (old.id,))
    old_dropoff = Stop(2, (old.id,), ())
    elevator = ElevatorSnapshot("A", 2, 0, (), None, None, 0, (old_pickup, old_dropoff))
    context = AllocationContext(0, Timing(100, 10), (elevator,), (old, request))

    # Either pickup order followed by either drop-off order costs 240 ms.
    assert InsertionAllocator().allocate(request, context) == AllocationDecision(
        "A", (Stop(0, (), (request.id,)), old_pickup, Stop(2, (request.id,), ()), old_dropoff)
    )


def test_baseline_accounts_for_remaining_dwell() -> None:
    request = PassengerRequest("new", 50, 0, 1)
    dwelling = ElevatorSnapshot("A", 1, 0, (), None, None, 200, ())
    idle = ElevatorSnapshot("B", 1, 1, (), None, None, 0, ())
    context = AllocationContext(50, Timing(100, 200), (dwelling, idle), (request,))

    assert BaselineAllocator().allocate(request, context) == AllocationDecision(
        "B", (Stop(0, (), (request.id,)), Stop(1, (request.id,), ()))
    )
