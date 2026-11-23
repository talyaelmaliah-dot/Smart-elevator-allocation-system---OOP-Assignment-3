# Smart-elevator-allocation-system---OOP-Assignment-3

Smart Elevator System for OOP Assignment 3. The goal is to minimize passenger journey time, measured from request submission to arrival at the destination.

## Project status

The architecture, JSON contract, and development plan are ready for review. Simulator, allocator, generator, GUI, and tests are planned implementation work.

- [Architecture and four-agent development plan](docs/architecture.md)
- [Simulation and request JSON Schema v1](schemas/simulation-v1.schema.json)
- [Coding, testing, and integration rules](AGENTS.md)

The planned stack is Python 3.11+, typed object-oriented components, pytest, and a Tkinter desktop interface. A future ESP32 adapter will exchange messages with the simulator over WiFi or BLE.
