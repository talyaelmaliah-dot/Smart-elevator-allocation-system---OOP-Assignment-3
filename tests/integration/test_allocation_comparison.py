from smart_elevator.allocation import BaselineAllocator, InsertionAllocator
from smart_elevator.contracts import ElevatorSpec, Scenario
from smart_elevator.domain import Building, Floor, PassengerRequest, Timing
from smart_elevator.simulator import Simulator


def test_insertion_reduces_total_journey_time_on_same_requests() -> None:
    requests = (
        PassengerRequest("R1", 0, 0, 4),
        PassengerRequest("R2", 1, 1, 3),
    )
    scenario = Scenario(
        Building(tuple(Floor(index) for index in range(5)), 0),
        Timing(100, 10),
        (ElevatorSpec("E1", 0, 2),),
        requests,
    )

    baseline = Simulator(scenario, requests, BaselineAllocator()).run()
    insertion = Simulator(scenario, requests, InsertionAllocator()).run()

    assert baseline.completed_count == insertion.completed_count == 2
    assert baseline.total_journey_ms == 410 + 929
    assert insertion.total_journey_ms == 430 + 319
    assert insertion.total_journey_ms < baseline.total_journey_ms
    assert baseline.snapshot.passengers[1].picked_up_at_ms == 720
    assert insertion.snapshot.passengers[1].picked_up_at_ms == 110
