# Architecture governance

Before changing architecture, named types, runtime state, modules, dependencies, ports, callbacks, or events:

1. Read `architecture/manifest.yaml`, `architecture/adoption.yaml`, `architecture/ARCHITECTURE.md`, accepted ADRs, and the baseline if present.
2. Before editing source, build the Boundary Design Table, Type Ownership Matrix, State Object Ownership Matrix, actual/intended dependency edges, and parent mappings.
3. Validate the planned manifest. An unresolved owner, authority, dependency, or mapping is `BLOCKED`.
4. Preserve every schema 1.0 through 2.1.0 requirement under schema 2.2.0, while retaining exact 2.1.0 compatibility.
5. Do not mark an ADR accepted without explicit user approval.
6. Update governance files, source, and tests together.
7. Treat `architecture/manifest.yaml` as the only editable description source. Do not hand-edit generated Architecture Description Views.
8. Use schema 2.2.0 for new projects (2.1.0 remains supported) and describe logical source sets, composition roots, modules, ports, events, named types and references, state objects, boundary mappings, source paths, symbols, L0/L1 flows, workloads, execution profiles/units/channels, workload-driven real-time scheduling studies, data access, microarchitecture, validation profiles, assurance scope, and any exact localized diagram summaries. Then run `python tools\architecture\architecture_cli.py render`.
9. For C/C++, require pinned libclang, a complete compilation database and target, all governed translation units, and AST PASS. Lexical scanning alone is not PASS.
10. Run every gate through the single `architecture_cli.py`; legacy checker, renderer, bootstrap, and analyzer scripts are internal and cannot be invoked directly.
11. Remediate discovered legacy violations by default. Use a temporary baseline only for exact, unexpired, non-AI-approved deferrals; Release requires a zero-entry baseline.

Use this command on Windows:

```powershell
python tools\architecture\architecture_cli.py gate --phase development --manifest architecture\manifest.yaml --adoption architecture\adoption.yaml --baseline architecture\baseline.yaml --format text
```

Treat exit `0` as pass, `1` as a MUST violation, and `2` as `BLOCKED` because configuration, capability, coverage, or parse evidence is incomplete.

Use `python tools\architecture\architecture_cli.py gate --phase release` in CI. The single gate rejects incomplete AST coverage, temporary baseline debt, and missing, changed, or obsolete generated pages.

For an existing project, also pass `--baseline architecture\baseline.yaml`. In CI, export the target branch's baseline to a temporary file and pass it as `--previous-baseline`; baseline growth is forbidden.
