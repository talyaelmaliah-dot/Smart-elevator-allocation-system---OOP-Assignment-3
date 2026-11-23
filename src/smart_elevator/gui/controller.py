from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ..contracts import Scenario, SimulationResult, SimulationSnapshot


class Simulation(Protocol):
    def snapshot(self) -> SimulationSnapshot: ...
    def step(self) -> SimulationSnapshot: ...


SimulationFactory = Callable[[], Simulation]
ScenarioLoader = Callable[[Path], tuple[Scenario, SimulationFactory]]


class Controller:
    def __init__(self, load_scenario: ScenarioLoader) -> None:
        self._load_scenario = load_scenario
        self._factory: SimulationFactory | None = None
        self._simulation: Simulation | None = None
        self.path: Path | None = None
        self.scenario: Scenario | None = None
        self.snapshot: SimulationSnapshot | None = None
        self.playing = False

    def load(self, path: Path) -> None:
        scenario, factory = self._load_scenario(path)
        simulation = factory()
        snapshot = simulation.snapshot()
        self.pause()
        self.path = path
        self.scenario = scenario
        self._factory = factory
        self._simulation = simulation
        self.snapshot = snapshot

    def play(self) -> None:
        self.playing = self.snapshot is not None and not self.snapshot.finished

    def pause(self) -> None:
        self.playing = False

    def step(self) -> None:
        self.pause()
        self._advance()

    def tick(self) -> None:
        if self.playing:
            self._advance()

    def reset(self) -> None:
        self.pause()
        if self._factory is not None:
            simulation = self._factory()
            self.snapshot = simulation.snapshot()
            self._simulation = simulation

    def _advance(self) -> None:
        if self._simulation is None or self.snapshot is None or self.snapshot.finished:
            return
        try:
            self.snapshot = self._simulation.step()
        except (ValueError, RuntimeError):
            self.pause()
            raise
        if self.snapshot.finished:
            self.pause()


def completed_metrics(snapshot: SimulationSnapshot) -> SimulationResult:
    count = total_journey = total_wait = max_journey = 0
    for passenger in snapshot.passengers:
        if passenger.arrived_at_ms is None or passenger.picked_up_at_ms is None:
            continue
        requested = passenger.request.requested_at_ms
        journey = passenger.arrived_at_ms - requested
        count += 1
        total_journey += journey
        total_wait += passenger.picked_up_at_ms - requested
        max_journey = max(max_journey, journey)
    return SimulationResult(
        snapshot,
        count,
        total_journey,
        total_journey / count if count else 0.0,
        total_wait / count if count else 0.0,
        max_journey,
    )
