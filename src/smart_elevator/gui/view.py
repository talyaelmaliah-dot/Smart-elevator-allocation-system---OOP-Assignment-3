from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..contracts import ElevatorSnapshot, PassengerProgress
from .controller import Controller, completed_metrics


def _car_status(car: ElevatorSnapshot, now_ms: int) -> str:
    if car.active_stop is not None:
        return f"To floor {car.active_stop.floor} (ETA {car.arrival_at_ms} ms)"
    if car.available_at_ms > now_ms:
        return f"Doors open until {car.available_at_ms} ms"
    return "Idle"


def _passenger_status(passenger: PassengerProgress) -> str:
    if passenger.arrived_at_ms is not None:
        return "Arrived"
    if passenger.picked_up_at_ms is not None:
        return "Onboard"
    if passenger.elevator_id is not None:
        return "Assigned"
    return "Waiting"


class ElevatorWindow:
    def __init__(self, root: tk.Tk, controller: Controller, allocator: str) -> None:
        self._root = root
        self._controller = controller
        self._allocator = allocator
        self._timer: str | None = None

        root.title("Smart Elevator")
        root.minsize(720, 520)
        body = ttk.Frame(root, padding=16)
        body.pack(fill="both", expand=True)

        controls = ttk.Frame(body)
        controls.pack(fill="x")
        ttk.Button(controls, text="Load scenario...", command=self._choose).pack(
            side="left", padx=(0, 12)
        )
        self._buttons: dict[str, ttk.Button] = {}
        for label, action in (
            ("Play", controller.play),
            ("Pause", controller.pause),
            ("Step", controller.step),
            ("Reset", controller.reset),
        ):
            button = ttk.Button(
                controls, text=label, command=lambda action=action: self._act(action)
            )
            button.pack(side="left", padx=(0, 4))
            self._buttons[label] = button

        self._status = ttk.Label(body)
        self._status.pack(anchor="w", pady=(12, 8))
        self._metrics = ttk.Label(body)
        self._metrics.pack(anchor="w", pady=(0, 8))

        self._floors = self._table(body, "Floors", (
            ("Floor", 130), ("Elevators at floor", 220), ("Waiting passengers", 220),
        ), height=6)
        self._cars = self._table(body, "Elevators", (
            ("Elevator", 90), ("Last floor", 80), ("State", 220),
            ("Occupancy", 80), ("Onboard passengers", 160),
        ), height=4)
        self._passengers = self._table(body, "Passengers", (
            ("Passenger", 90), ("From", 54), ("To", 54), ("State", 85),
            ("Elevator", 80), ("Wait (ms)", 80), ("Ride (ms)", 80),
            ("Journey (ms)", 90),
        ), height=8)
        self._render()

    @staticmethod
    def _table(
        parent: ttk.Frame, title: str, columns: tuple[tuple[str, int], ...], height: int
    ) -> ttk.Treeview:
        frame = ttk.LabelFrame(parent, text=title, padding=4)
        frame.pack(fill="both", expand=True, pady=(0, 8))
        names = tuple(name for name, _ in columns)
        table = ttk.Treeview(frame, columns=names, show="headings", height=height)
        for name, width in columns:
            table.heading(name, text=name)
            table.column(name, width=width, minwidth=width // 2)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        return table

    @staticmethod
    def _update_rows(
        table: ttk.Treeview, rows: Iterable[tuple[str | int, ...]]
    ) -> None:
        position = table.yview()[0]
        table.delete(*table.get_children())
        for row in rows:
            table.insert("", "end", values=row)
        table.yview_moveto(position)

    def _choose(self) -> None:
        self._act(self._controller.pause)
        path = filedialog.askopenfilename(
            parent=self._root,
            title="Load scenario",
            filetypes=(("JSON scenarios", "*.json"), ("All files", "*")),
        )
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        self._act(lambda: self._controller.load(path))

    def _act(self, action: Callable[[], None]) -> None:
        if self._timer is not None:
            self._root.after_cancel(self._timer)
            self._timer = None
        try:
            action()
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Simulation error", str(exc), parent=self._root)
        self._render()
        if self._controller.playing:
            self._timer = self._root.after(500, self._tick)

    def _tick(self) -> None:
        self._timer = None
        self._act(self._controller.tick)

    def _render(self) -> None:
        controller = self._controller
        snapshot = controller.snapshot
        can_advance = snapshot is not None and not snapshot.finished
        for label, enabled in (
            ("Play", can_advance and not controller.playing),
            ("Pause", controller.playing),
            ("Step", can_advance and not controller.playing),
            ("Reset", snapshot is not None),
        ):
            self._buttons[label].state(["!disabled" if enabled else "disabled"])
        if snapshot is None or controller.scenario is None or controller.path is None:
            self._status.configure(text=f"Load a scenario to begin  |  {self._allocator}")
            return

        state = "Finished" if snapshot.finished else (
            "Running" if controller.playing else "Paused"
        )
        self._status.configure(
            text=f"{controller.path.name}  |  {self._allocator}  |  "
            f"{state}  |  {snapshot.now_ms} ms"
        )
        metrics = completed_metrics(snapshot)
        self._metrics.configure(
            text=f"Completed: {metrics.completed_count}   "
            f"Total journey: {metrics.total_journey_ms} ms   "
            f"Mean journey: {metrics.mean_journey_ms:.1f} ms   "
            f"Mean wait: {metrics.mean_wait_ms:.1f} ms   "
            f"Max journey: {metrics.max_journey_ms} ms"
        )
        parked: dict[int, list[str]] = defaultdict(list)
        car_rows = []
        for car in snapshot.elevators:
            if car.active_stop is None:
                parked[car.last_floor].append(car.id)
            car_rows.append((
                car.id, car.last_floor, _car_status(car, snapshot.now_ms),
                f"{len(car.onboard_ids)}/{car.capacity}", ", ".join(car.onboard_ids),
            ))
        waiting: dict[int, list[str]] = defaultdict(list)
        passenger_rows = []
        for passenger in snapshot.passengers:
            request = passenger.request
            pickup, arrival = passenger.picked_up_at_ms, passenger.arrived_at_ms
            if pickup is None:
                waiting[request.origin].append(request.id)
            passenger_rows.append((
                request.id, request.origin, request.destination,
                _passenger_status(passenger), passenger.elevator_id or "-",
                pickup - request.requested_at_ms if pickup is not None else "-",
                arrival - pickup if arrival is not None and pickup is not None else "-",
                arrival - request.requested_at_ms if arrival is not None else "-",
            ))
        building = controller.scenario.building
        self._update_rows(self._floors, (
            (
                f"{floor.index} (lobby)" if floor.index == building.lobby_floor else floor.index,
                ", ".join(parked[floor.index]),
                ", ".join(waiting[floor.index]),
            )
            for floor in reversed(building.floors)
        ))
        self._update_rows(self._cars, car_rows)
        self._update_rows(self._passengers, passenger_rows)
