# Agent instructions

## Scope and style

- Read [the architecture](docs/architecture.md) and [the v1 schema](schemas/simulation-v1.schema.json) before implementing. Each branch owns the paths listed in the architecture.
- Use Python 3.11+, four-space indentation, PEP 8 naming, and type hints on public methods and boundary data. Use dataclasses for value objects and protocols for replaceable dependencies. Use frozen dataclasses and tuples for published snapshots.
- Use integer milliseconds throughout the core. Keep wall-clock timing, UI scheduling, and I/O at the edges. Use a local seeded RNG for traffic generation.
- Keep domain and contract modules free of imports from the generator, simulator, allocator, GUI, and ESP32 adapter. Wire concrete components in the application entry point. Do not mutate state through an allocator input or a UI snapshot.

## Testing

- Use pytest. After packaging is implemented, install with `python -m pip install -e '.[dev]'` and run `python -m pytest` from the repository root.
- Put component tests under the branch-owned `tests/unit/` directory. Put end-to-end tests in the branch-owned `tests/integration/` files. Cover deterministic replay, invalid inputs, event ordering, capacity, and journey-time accounting as applicable.
- Use fixed seeds and hand-checkable fixtures. Avoid real sleeps, display-server dependencies in automated tests, and hardware or network dependencies in the core suite. Exercise the GUI separately with the manual smoke procedure in the architecture.

## Integration

- Branch from the agreed planning commit. Keep changes within the assigned paths. The integration lead owns shared documentation, schema changes, and cross-branch contract decisions.
- Propose interface changes before editing. Update the signatures, schema when applicable, and affected contract tests together. Build against local fakes while dependencies are pending and remove temporary substitutes before merging.
- The lead merges the contract and packaging foundation first, then simulator, allocator, and UI branches. Rebase each pending branch onto the current integration tip and run its tests. Run the full suite on the integrated branch and review the baseline comparison and GUI smoke result before release.
