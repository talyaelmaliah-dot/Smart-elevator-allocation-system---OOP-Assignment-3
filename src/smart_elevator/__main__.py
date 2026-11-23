from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from .allocation import BaselineAllocator, InsertionAllocator
from .contracts import GeneratedTraffic, Scenario
from .generator import RequestGenerator
from .scenario import load_scenario
from .simulator import Simulator

ALLOCATORS = {"insertion": InsertionAllocator, "baseline": BaselineAllocator}


def prepare_scenario(
    path: Path, allocator: str
) -> tuple[Scenario, Callable[[], Simulator]]:
    scenario = load_scenario(path)
    traffic = scenario.traffic
    requests = (
        RequestGenerator().generate(scenario.building, traffic)
        if isinstance(traffic, GeneratedTraffic)
        else traffic
    )
    allocator_factory = ALLOCATORS[allocator]

    def create_simulator() -> Simulator:
        return Simulator(scenario, requests, allocator_factory())

    return scenario, create_simulator


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the smart elevator simulation.")
    parser.add_argument("scenario", nargs="?", type=Path, help="scenario JSON path")
    parser.add_argument("--headless", action="store_true", help="print metrics as JSON")
    parser.add_argument("--allocator", choices=ALLOCATORS, default="insertion")
    args = parser.parse_args(argv)

    if args.headless:
        if args.scenario is None:
            parser.error("--headless requires a scenario path")
        try:
            _, create_simulator = prepare_scenario(args.scenario, args.allocator)
            result = create_simulator().run()
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(1, f"{parser.prog}: {exc}\n")
        print(json.dumps({
            "completed_count": result.completed_count,
            "total_journey_ms": result.total_journey_ms,
            "mean_journey_ms": result.mean_journey_ms,
            "mean_wait_ms": result.mean_wait_ms,
            "max_journey_ms": result.max_journey_ms,
        }))
        return 0

    try:
        from tkinter import TclError, Tk
    except ImportError as exc:
        parser.exit(1, f"{parser.prog}: Tkinter is unavailable ({exc})\n")

    from .gui.controller import Controller
    from .gui.view import ElevatorWindow

    try:
        root = Tk()
    except TclError as exc:
        parser.exit(1, f"{parser.prog}: could not open the GUI ({exc})\n")
    controller = Controller(lambda path: prepare_scenario(path, args.allocator))
    window = ElevatorWindow(root, controller, args.allocator)
    if args.scenario is not None:
        window.load(args.scenario)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
