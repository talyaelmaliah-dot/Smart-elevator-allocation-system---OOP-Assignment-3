import pytest

from smart_elevator.contracts import (
    AllocationContext,
    AllocationDecision,
    ElevatorSpec,
    Scenario,
    Stop,
)
from smart_elevator.domain import Building, Floor, PassengerRequest, Timing
from smart_elevator.simulator import Simulator


def scenario(*elevators: ElevatorSpec) -> Scenario:
    return Scenario(
        Building(tuple(Floor(index) for index in range(4)), 0),
        Timing(10, 5),
        elevators or (ElevatorSpec("E", 0, 1),),
        (),
    )


def stops(request: PassengerRequest) -> tuple[Stop, Stop]:
    return Stop(request.origin, (), (request.id,)), Stop(
        request.destination, (request.id,), ()
    )


class AppendAllocator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, AllocationContext]] = []

    def allocate(
        self, request: PassengerRequest, context: AllocationContext
    ) -> AllocationDecision:
        self.calls.append((request.id, context))
        car = context.elevators[0]
        return AllocationDecision(car.id, car.pending_stops + stops(request))


def test_arrival_and_dwell_end_precede_submissions_at_same_time() -> None:
    class AllocateByRequest(AppendAllocator):
        def allocate(
            self, request: PassengerRequest, context: AllocationContext
        ) -> AllocationDecision:
            self.calls.append((request.id, context))
            first, second = context.elevators
            car = second if request.id == "b" else first
            return AllocationDecision(car.id, car.pending_stops + stops(request))

    allocator = AllocateByRequest()
    simulator = Simulator(
        scenario(ElevatorSpec("Z", 3, 1), ElevatorSpec("A", 0, 1)),
        (
            PassengerRequest("d", 10, 1, 2),
            PassengerRequest("b", 5, 3, 2),
            PassengerRequest("c", 10, 2, 0),
            PassengerRequest("a", 0, 1, 0),
        ),
        allocator,
    )
    simulator.step()
    simulator.step()
    snapshot = simulator.step()
    assert [id_ for id_, _ in allocator.calls] == ["a", "b", "c", "d"]
    context = allocator.calls[2][1]
    assert [request.id for request in context.active_requests] == ["a", "b", "c", "d"]
    first, second = context.elevators
    assert (first.id, first.last_floor, first.onboard_ids) == ("A", 1, ("a",))
    assert first.active_stop is None
    assert first.available_at_ms == 15
    assert (second.id, second.available_at_ms) == ("Z", 0)
    assert allocator.calls[3][1].elevators[0].pending_stops == (
        Stop(0, ("a",), ()),
        Stop(2, (), ("c",)),
        Stop(0, ("c",), ()),
    )
    assert snapshot.elevators[1].arrival_at_ms == 20


def test_same_floor_stops_have_separate_dwell_and_exact_metrics() -> None:
    allocator = AppendAllocator()
    simulator = Simulator(
        scenario(),
        (PassengerRequest("b", 0, 1, 0), PassengerRequest("a", 0, 0, 1)),
        allocator,
    )
    pickup = simulator.step()
    assert pickup.now_ms == 0
    assert pickup.passengers[0].picked_up_at_ms == 0
    assert pickup.elevators[0].available_at_ms == 5
    moving = simulator.step().elevators[0]
    assert (moving.last_floor, moving.arrival_at_ms, moving.available_at_ms) == (0, 15, 20)
    arrival = simulator.step()
    assert arrival.passengers[0].arrived_at_ms == 15
    assert arrival.passengers[1].picked_up_at_ms is None
    second_pickup = simulator.step()
    assert second_pickup.passengers[1].picked_up_at_ms == 20
    assert second_pickup.elevators[0].available_at_ms == 25
    result = simulator.run()
    assert result.snapshot.now_ms == 40
    assert result.snapshot.finished
    assert result.completed_count == 2
    assert result.total_journey_ms == 50
    assert result.mean_journey_ms == 25
    assert result.mean_wait_ms == 10
    assert result.max_journey_ms == 35
    assert simulator.step() == result.snapshot
    assert pickup.passengers[0].arrived_at_ms is None


def test_immediate_pickup_retries_waiting_request_before_time_advances() -> None:
    class DeferUntilPickup(AppendAllocator):
        def allocate(
            self, request: PassengerRequest, context: AllocationContext
        ) -> AllocationDecision | None:
            self.calls.append((request.id, context))
            car = context.elevators[0]
            if request.id == "b" and not car.onboard_ids:
                return None
            return AllocationDecision(car.id, car.pending_stops + stops(request))

    allocator = DeferUntilPickup()
    simulator = Simulator(
        scenario(),
        (PassengerRequest("b", 0, 1, 0), PassengerRequest("a", 0, 0, 1)),
        allocator,
    )
    snapshot = simulator.step()
    assert [(id_, ctx.now_ms) for id_, ctx in allocator.calls] == [
        ("a", 0), ("b", 0), ("b", 0)
    ]
    assert snapshot.passengers[1].elevator_id == "E"


@pytest.mark.parametrize("invalid", ["capacity", "missing_stop", "wrong_order", "unknown"])
def test_invalid_decision_keeps_existing_route(invalid: str) -> None:
    class InvalidDecision:
        def allocate(
            self, request: PassengerRequest, context: AllocationContext
        ) -> AllocationDecision:
            car = context.elevators[0]
            pickup, dropoff = stops(request)
            if request.id == "a":
                return AllocationDecision(car.id, (pickup, dropoff))
            if invalid == "capacity":
                return AllocationDecision(car.id, (pickup, dropoff) + car.pending_stops)
            if invalid == "missing_stop":
                return AllocationDecision(car.id, (pickup, dropoff))
            if invalid == "wrong_order":
                return AllocationDecision(car.id, car.pending_stops + (dropoff, pickup))
            return AllocationDecision("unknown", car.pending_stops + (pickup, dropoff))

    simulator = Simulator(
        scenario(),
        (PassengerRequest("a", 0, 1, 2), PassengerRequest("b", 6, 1, 3)),
        InvalidDecision(),
    )
    moving = simulator.step().elevators[0]
    with pytest.raises(ValueError):
        simulator.step()
    assert simulator.snapshot().elevators[0] == moving
    assert simulator.snapshot().passengers[1].elevator_id is None


def test_deferred_request_with_no_future_events_fails() -> None:
    class AlwaysDefer:
        def allocate(
            self, request: PassengerRequest, context: AllocationContext
        ) -> None:
            return None

    simulator = Simulator(scenario(), (PassengerRequest("a", 0, 0, 1),), AlwaysDefer())
    with pytest.raises(RuntimeError, match="unfinished requests"):
        simulator.run()


@pytest.mark.parametrize(
    "request_tuple",
    [
        (PassengerRequest("a", 0, 0, 1), PassengerRequest("a", 10, 0, 1)),
        (PassengerRequest("", 0, 0, 1),),
        (PassengerRequest("a", -1, 0, 1),),
        (PassengerRequest("a", 0, 0, 4),),
        (PassengerRequest("a", 0, 0, 0),),
    ],
)
def test_validates_materialized_requests(
    request_tuple: tuple[PassengerRequest, ...],
) -> None:
    with pytest.raises(ValueError):
        Simulator(scenario(), request_tuple, AppendAllocator())


def test_empty_workload_is_already_finished() -> None:
    simulator = Simulator(scenario(), (), AppendAllocator())
    result = simulator.run()
    assert result.snapshot == simulator.step()
    assert result.snapshot.finished
    assert result.completed_count == result.total_journey_ms == result.max_journey_ms == 0
    assert result.mean_journey_ms == result.mean_wait_ms == 0.0
