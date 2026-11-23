from pathlib import Path

import pytest

from smart_elevator.contracts import PassengerProgress, Scenario, SimulationSnapshot
from smart_elevator.domain import PassengerRequest
from smart_elevator.gui.controller import Controller, SimulationFactory, completed_metrics
from smart_elevator.scenario import load_scenario

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "explicit.json"


class FakeSimulation:
    def __init__(self) -> None:
        self.steps = 0

    def snapshot(self) -> SimulationSnapshot:
        return SimulationSnapshot(self.steps * 100, (), (), self.steps == 3)

    def step(self) -> SimulationSnapshot:
        self.steps += 1
        return self.snapshot()


def test_controls_replay_from_initial_snapshot() -> None:
    scenario = load_scenario(EXAMPLE)
    controller = Controller(lambda path: (scenario, FakeSimulation))
    controller.play()
    controller.tick()
    assert not controller.playing
    assert controller.snapshot is None

    controller.load(EXAMPLE)
    initial = controller.snapshot
    assert initial == SimulationSnapshot(0, (), (), False)
    controller.step()
    first_step = controller.snapshot
    assert first_step == SimulationSnapshot(100, (), (), False)
    controller.play()
    controller.tick()
    controller.pause()
    controller.tick()
    assert controller.snapshot == SimulationSnapshot(200, (), (), False)
    controller.play()
    controller.tick()
    assert controller.snapshot == SimulationSnapshot(300, (), (), True)
    assert not controller.playing
    controller.step()
    assert controller.snapshot.finished

    controller.reset()
    assert controller.snapshot == initial
    controller.step()
    assert controller.snapshot == first_step


def test_failed_load_preserves_current_run_and_successful_load_pauses() -> None:
    scenario = load_scenario(EXAMPLE)

    def load(path: Path) -> tuple[Scenario, SimulationFactory]:
        if path != EXAMPLE:
            raise ValueError("invalid scenario")
        return scenario, FakeSimulation

    controller = Controller(load)
    controller.load(EXAMPLE)
    controller.step()
    controller.play()
    with pytest.raises(ValueError, match="invalid scenario"):
        controller.load(Path("invalid.json"))
    assert controller.path == EXAMPLE
    assert controller.playing
    assert controller.snapshot == SimulationSnapshot(100, (), (), False)

    controller.load(EXAMPLE)
    controller.tick()
    assert not controller.playing
    assert controller.snapshot == SimulationSnapshot(0, (), (), False)


def test_metrics_include_only_completed_passengers() -> None:
    waiting = PassengerProgress(PassengerRequest("R1", 0, 0, 1), None, None, None)
    arrived = PassengerProgress(PassengerRequest("R2", 100, 0, 1), "E1", 300, 900)
    empty = completed_metrics(SimulationSnapshot(0, (), (), False))
    assert empty.completed_count == empty.mean_journey_ms == empty.mean_wait_ms == 0

    result = completed_metrics(SimulationSnapshot(900, (), (waiting, arrived), False))
    assert result.completed_count == 1
    assert result.total_journey_ms == result.mean_journey_ms == result.max_journey_ms == 800
    assert result.mean_wait_ms == 200
