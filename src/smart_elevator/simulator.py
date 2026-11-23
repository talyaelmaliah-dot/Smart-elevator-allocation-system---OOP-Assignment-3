from __future__ import annotations

from dataclasses import replace
from enum import IntEnum
from heapq import heappop, heappush
from itertools import count

from .contracts import (
    AllocationContext,
    AllocationDecision,
    Allocator,
    PassengerProgress,
    Scenario,
    SimulationResult,
    SimulationSnapshot,
    Stop,
)
from .domain import Elevator, PassengerRequest


class _Event(IntEnum):
    ARRIVAL = 0
    DWELL_END = 1
    SUBMISSION = 2


class Simulator:
    """Advance a materialized workload one event timestamp at a time."""

    def __init__(
        self,
        scenario: Scenario,
        requests: tuple[PassengerRequest, ...],
        allocator: Allocator,
    ) -> None:
        self._scenario = scenario
        self._allocator = allocator
        self._now_ms = 0
        self._sequence = count()
        self._events: list[tuple[int, _Event, str, int]] = []
        self._fleet = {
            spec.id: Elevator(spec.id, spec.start_floor, spec.capacity)
            for spec in sorted(scenario.elevators, key=lambda spec: spec.id)
        }
        self._requests: dict[str, PassengerRequest] = {}
        self._passengers: dict[str, PassengerProgress] = {}
        self._waiting: dict[str, PassengerRequest] = {}
        self._active: dict[str, PassengerRequest] = {}
        self._completed = 0
        for request in requests:
            if not isinstance(request.id, str) or not request.id:
                raise ValueError("request ID must be a nonempty string")
            if request.id in self._requests:
                raise ValueError(f"duplicate request ID: {request.id!r}")
            if type(request.requested_at_ms) is not int or request.requested_at_ms < 0:
                raise ValueError(f"invalid request timestamp for {request.id!r}")
            scenario.building.floor(request.origin)
            scenario.building.floor(request.destination)
            if request.origin == request.destination:
                raise ValueError(f"request {request.id!r} has identical endpoints")
            self._requests[request.id] = request
            self._schedule(request.requested_at_ms, _Event.SUBMISSION, request.id)

    def _schedule(self, time_ms: int, event: _Event, id_: str) -> None:
        heappush(self._events, (time_ms, event, id_, next(self._sequence)))

    def snapshot(self) -> SimulationSnapshot:
        return SimulationSnapshot(
            now_ms=self._now_ms,
            elevators=tuple(car.snapshot() for car in self._fleet.values()),
            passengers=tuple(self._passengers.values()),
            finished=not self._events and self._completed == len(self._requests),
        )

    def step(self) -> SimulationSnapshot:
        if not self._events:
            return self._snapshot_after_step()

        self._now_ms = self._events[0][0]
        while self._events and self._events[0][0] == self._now_ms:
            _, event, id_, _ = heappop(self._events)
            if event == _Event.ARRIVAL:
                car = self._fleet[id_]
                assert car.active_stop is not None
                self._serve(car, car.active_stop)
            elif event == _Event.DWELL_END:
                self._fleet[id_].available_at_ms = 0
            else:
                request = self._requests[id_]
                self._passengers[id_] = PassengerProgress(request, None, None, None)
                self._waiting[id_] = request
                self._active[id_] = request

        while True:
            self._dispatch()
            if not self._start_ready_cars():
                return self._snapshot_after_step()

    def _snapshot_after_step(self) -> SimulationSnapshot:
        if not self._events and self._completed != len(self._requests):
            raise RuntimeError("event queue exhausted with unfinished requests")
        return self.snapshot()

    def _dispatch(self) -> None:
        for request in tuple(self._waiting.values()):
            context = AllocationContext(
                self._now_ms,
                self._scenario.timing,
                tuple(car.snapshot() for car in self._fleet.values()),
                tuple(self._active.values()),
            )
            decision = self._allocator.allocate(request, context)
            if decision is not None:
                car = self._validate_decision(request, decision)
                car.pending_stops = decision.pending_stops
                self._passengers[request.id] = replace(
                    self._passengers[request.id], elevator_id=car.id
                )
                del self._waiting[request.id]

    def _validate_decision(
        self, request: PassengerRequest, decision: AllocationDecision
    ) -> Elevator:
        car = self._fleet.get(decision.elevator_id)
        if car is None:
            raise ValueError(f"unknown elevator: {decision.elevator_id!r}")
        route = decision.pending_stops
        if not isinstance(route, tuple) or len(route) != len(car.pending_stops) + 2:
            raise ValueError("allocation must insert exactly two stops")

        invalid_route = "allocation must preserve pending stops and insert pickup before drop-off"
        pickup = Stop(request.origin, (), (request.id,))
        dropoff = Stop(request.destination, (request.id,), ())
        added = iter((pickup, dropoff))
        next_added = next(added, None)
        original = iter(car.pending_stops)
        next_original = next(original, None)
        for stop in route:
            if next_original is not None and stop == next_original:
                next_original = next(original, None)
            elif next_added is not None and stop == next_added:
                next_added = next(added, None)
            else:
                raise ValueError(invalid_route)
        if next_original is not None or next_added is not None:
            raise ValueError(invalid_route)

        stops = route if car.active_stop is None else (car.active_stop,) + route
        load = len(car.onboard_ids)
        for stop in stops:
            load += len(stop.pickup_ids) - len(stop.dropoff_ids)
            if load > car.capacity:
                raise ValueError(f"allocation exceeds capacity of elevator {car.id!r}")
        return car

    def _start_ready_cars(self) -> bool:
        passenger_state_changed = False
        for car in self._fleet.values():
            if (
                car.active_stop is not None
                or car.available_at_ms
                or not car.pending_stops
            ):
                continue
            stop, *remaining = car.pending_stops
            car.pending_stops = tuple(remaining)
            distance = abs(stop.floor - car.last_floor)
            if distance == 0:
                self._serve(car, stop)
                if stop.pickup_ids or stop.dropoff_ids:
                    passenger_state_changed = True
            else:
                travel_ms = distance * self._scenario.timing.travel_ms_per_floor
                arrival = self._now_ms + travel_ms
                car.active_stop = stop
                car.arrival_at_ms = arrival
                car.available_at_ms = arrival + self._scenario.timing.door_dwell_ms
                self._schedule(arrival, _Event.ARRIVAL, car.id)
        return passenger_state_changed

    def _serve(self, car: Elevator, stop: Stop) -> None:
        car.last_floor = stop.floor
        car.active_stop = None
        car.arrival_at_ms = None
        for id_ in stop.dropoff_ids:
            car.onboard_ids.remove(id_)
            self._passengers[id_] = replace(
                self._passengers[id_], arrived_at_ms=self._now_ms
            )
            del self._active[id_]
            self._completed += 1
        if len(car.onboard_ids) + len(stop.pickup_ids) > car.capacity:
            raise RuntimeError(f"capacity exceeded in elevator {car.id!r}")
        for id_ in stop.pickup_ids:
            car.onboard_ids.add(id_)
            self._passengers[id_] = replace(
                self._passengers[id_], picked_up_at_ms=self._now_ms
            )
        car.available_at_ms = self._now_ms + self._scenario.timing.door_dwell_ms
        self._schedule(car.available_at_ms, _Event.DWELL_END, car.id)

    def run(self) -> SimulationResult:
        snapshot = self.snapshot()
        while not snapshot.finished:
            snapshot = self.step()

        total_journey = total_wait = max_journey = 0
        for passenger in snapshot.passengers:
            requested = passenger.request.requested_at_ms
            assert passenger.arrived_at_ms is not None
            assert passenger.picked_up_at_ms is not None
            journey = passenger.arrived_at_ms - requested
            total_journey += journey
            total_wait += passenger.picked_up_at_ms - requested
            max_journey = max(max_journey, journey)
        count = self._completed
        return SimulationResult(
            snapshot,
            count,
            total_journey,
            total_journey / count if count else 0.0,
            total_wait / count if count else 0.0,
            max_journey,
        )
