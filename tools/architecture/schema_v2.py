"""Schema 2.1/2.2 type-governed architecture and execution validation."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from check_architecture import (
    BANNED_AI_APPROVERS,
    DESCRIPTION_SCHEMA_VERSION,
    DESCRIPTION_STANDARD_VERSION,
    SCHEMA_VERSION,
    STANDARD_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Diagnostic,
    ManifestError,
    _diag,
    _is_nonempty_string,
    load_yaml,
)
from schema_description import (
    ID_PATTERN,
    PROTECTED_RULES,
    validate_description_manifest,
)
from type_catalog import validate_type_catalog
from state_catalog import validate_state_catalog
from boundary_catalog import validate_boundary_catalog
from source_sets import validate_manifest_source_paths, validate_source_sets
from realtime_analysis import analyze_realtime_profile


TIMING_CLASSES = {"hard-real-time", "soft-real-time", "best-effort"}
PROFILE_STATUSES = {"legacy-review", "proposed", "accepted", "superseded"}
UNIT_KINDS = {"interrupt", "event-loop", "dedicated-task", "worker-pool", "async-executor", "process"}
OVERLOAD_POLICIES = {"reject", "backpressure", "drop", "coalesce", "degrade", "fail-safe"}
OPTIMIZATION_TIERS = {"tier-0", "tier-1", "tier-2"}
ASSURANCE_SCOPES = {"functional-compatibility", "performance", "real-time"}
REQUIRED_TIER1_FIELDS = {
    "working_set",
    "memory_traffic",
    "branch_predictability",
    "simd_dependencies",
    "parallelism",
    "blocking_bounds",
}
REQUIRED_ACCEPTED_TARGET_FIELDS = {"platform", "cpu", "runtime", "compiler"}


def _list(value: Any, diagnostics: list[Diagnostic], rule: str, location: str) -> list[Any]:
    if not isinstance(value, list):
        _diag(diagnostics, rule, location, "must be a list", configuration=True)
        return []
    return value


def _mapping(value: Any, diagnostics: list[Diagnostic], rule: str, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _diag(diagnostics, rule, location, "must be a mapping", configuration=True)
        return {}
    return value


def _nonempty_list(value: Any, diagnostics: list[Diagnostic], rule: str, location: str) -> list[Any]:
    parsed = _list(value, diagnostics, rule, location)
    if not parsed:
        _diag(diagnostics, rule, location, "must not be empty", configuration=True)
    return parsed


def _index(
    values: list[Any],
    diagnostics: list[Diagnostic],
    rule: str,
    location: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(values):
        item_location = f"{location}[{index}]"
        item = _mapping(raw, diagnostics, rule, item_location)
        identifier = item.get("id")
        if not _is_nonempty_string(identifier) or not ID_PATTERN.fullmatch(str(identifier)):
            _diag(diagnostics, rule, f"{item_location}.id", "must be a stable lowercase identifier", configuration=True)
            continue
        if str(identifier) in result:
            _diag(diagnostics, rule, f"{item_location}.id", f"duplicate ID {identifier!r}", configuration=True)
            continue
        result[str(identifier)] = item
    return result


def _refs(
    values: Any,
    known: dict[str, Any],
    diagnostics: list[Diagnostic],
    rule: str,
    location: str,
    *,
    required: bool = False,
) -> list[str]:
    parsed = _list(values, diagnostics, rule, location)
    if required and not parsed:
        _diag(diagnostics, rule, location, "must not be empty", configuration=True)
    result: list[str] = []
    for index, value in enumerate(parsed):
        if not _is_nonempty_string(value):
            _diag(diagnostics, rule, f"{location}[{index}]", "must be a non-empty ID", configuration=True)
        elif str(value) not in known:
            _diag(diagnostics, rule, f"{location}[{index}]", f"unknown reference {value!r}")
        else:
            result.append(str(value))
    return result


def _has_metric(workload: dict[str, Any], metric: str) -> bool:
    return any(isinstance(item, dict) and item.get("metric") == metric for item in workload.get("budgets", []))


def _valid_human_approval(approval: Any) -> bool:
    if not isinstance(approval, dict):
        return False
    words = set(re.findall(r"[a-z]+", str(approval.get("approved_by", "")).lower()))
    return (
        _is_nonempty_string(approval.get("approved_by"))
        and _is_nonempty_string(approval.get("approval_date"))
        and _is_nonempty_string(approval.get("approval_reference"))
        and not words.intersection(BANNED_AI_APPROVERS)
    )


def _apply_governance(
    diagnostics: list[Diagnostic],
    data: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None,
    previous_baseline_path: Path | None,
) -> None:
    valid_exceptions: list[dict[str, Any]] = []
    for raw in data.get("adr_exceptions", []):
        if not isinstance(raw, dict) or raw.get("status") != "accepted":
            continue
        words = set(re.findall(r"[a-z]+", str(raw.get("approved_by", "")).lower()))
        adr_path = manifest_path.parent / str(raw.get("adr", ""))
        if (
            _is_nonempty_string(raw.get("rule_id"))
            and _is_nonempty_string(raw.get("scope"))
            and _is_nonempty_string(raw.get("approval_reference"))
            and not words.intersection(BANNED_AI_APPROVERS)
            and adr_path.is_file()
        ):
            valid_exceptions.append(raw)

    baseline_entries: set[tuple[str, str]] = set()
    if baseline_path is not None:
        try:
            baseline = load_yaml(baseline_path)
            if baseline.get("schema_version") != data.get("schema_version"):
                _diag(diagnostics, "BAS001", str(baseline_path), "baseline schema version mismatch", configuration=True)
            entries = baseline.get("violations")
            if not isinstance(entries, list):
                _diag(diagnostics, "BAS002", str(baseline_path), "violations must be a list", configuration=True)
            else:
                for entry in entries:
                    if isinstance(entry, dict) and _is_nonempty_string(entry.get("rule_id")) and _is_nonempty_string(entry.get("location")):
                        baseline_entries.add((str(entry["rule_id"]), str(entry["location"])))
                    else:
                        _diag(diagnostics, "BAS003", str(baseline_path), "invalid baseline entry", configuration=True)
        except ManifestError as exc:
            _diag(diagnostics, "BAS000", str(baseline_path), str(exc), configuration=True)

    if previous_baseline_path is not None:
        try:
            previous = load_yaml(previous_baseline_path)
            previous_entries = {
                (str(item["rule_id"]), str(item["location"]))
                for item in previous.get("violations", [])
                if isinstance(item, dict) and "rule_id" in item and "location" in item
            }
            for rule_id, location in sorted(baseline_entries.difference(previous_entries)):
                _diag(diagnostics, "BAS004", f"{rule_id}:{location}", "baseline growth is forbidden")
        except ManifestError as exc:
            _diag(diagnostics, "BAS000", str(previous_baseline_path), str(exc), configuration=True)

    for diagnostic in diagnostics:
        if (
            diagnostic.configuration
            or diagnostic.rule_id in PROTECTED_RULES
            or diagnostic.rule_id.startswith("SCHED")
            or diagnostic.disposition != "active"
        ):
            continue
        if (diagnostic.rule_id, diagnostic.location) in baseline_entries:
            diagnostic.disposition = "baseline"
            continue
        for exception in valid_exceptions:
            if diagnostic.rule_id == exception["rule_id"] and diagnostic.location.startswith(str(exception["scope"])):
                diagnostic.disposition = f"adr:{exception['adr']}"
                break


def validate_manifest_v2(
    data: dict[str, Any],
    manifest_path: Path,
    baseline_path: Path | None = None,
    previous_baseline_path: Path | None = None,
    *,
    check_docs: bool = False,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    schema_version = data.get("schema_version")
    standard_version = data.get("standard_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _diag(
            diagnostics,
            "VER001",
            "schema_version",
            f"must be one of {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}",
            configuration=True,
        )
    if standard_version != schema_version:
        _diag(
            diagnostics,
            "VER001",
            "standard_version",
            "standard_version and schema_version must be an exact supported pair",
            configuration=True,
        )

    projected = copy.deepcopy(data)
    projected["standard_version"] = DESCRIPTION_STANDARD_VERSION
    projected["schema_version"] = DESCRIPTION_SCHEMA_VERSION
    for field in (
        "workloads",
        "execution_profiles",
        "execution_units",
        "execution_mappings",
        "execution_channels",
        "data_access_profiles",
        "microarchitecture_profiles",
        "platform_variants",
        "realtime_scheduling_studies",
        "validation_profiles",
        "rtos_design_studies",
    ):
        projected.pop(field, None)
    projected.pop("types", None)
    projected.pop("type_exclusions", None)
    projected.pop("state_objects", None)
    projected.pop("boundary_mappings", None)
    projected.pop("source_sets", None)
    projected.pop("composition_roots", None)
    projected.pop("python_analyzer", None)
    diagnostics.extend(
        validate_description_manifest(projected, manifest_path, check_docs=False)
    )
    diagnostics.extend(validate_type_catalog(data, manifest_path))
    diagnostics.extend(validate_state_catalog(data, manifest_path))
    diagnostics.extend(validate_boundary_catalog(data, manifest_path))
    diagnostics.extend(validate_source_sets(data))
    diagnostics.extend(validate_manifest_source_paths(data))
    modules = {
        str(item.get("id")): item
        for item in data.get("modules", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    diagram_language = project.get("diagram_language")
    if schema_version == "2.2.0":
        if diagram_language is not None and (
            not _is_nonempty_string(diagram_language)
            or re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", str(diagram_language))
            is None
        ):
            _diag(
                diagnostics,
                "DESC013",
                "project.diagram_language",
                "must be a non-empty BCP 47-style language tag",
                configuration=True,
            )
        for module_id, module in modules.items():
            description = (
                module.get("description")
                if isinstance(module.get("description"), dict)
                else {}
            )
            summaries = description.get("diagram_summaries")
            location = f"{module_id}.description.diagram_summaries"
            if summaries is not None and not isinstance(summaries, dict):
                _diag(
                    diagnostics,
                    "DESC013",
                    location,
                    "must be a locale-keyed mapping",
                    configuration=True,
                )
                summaries = {}
            if isinstance(summaries, dict):
                for locale, summary in summaries.items():
                    if (
                        not _is_nonempty_string(locale)
                        or re.fullmatch(
                            r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*",
                            str(locale),
                        )
                        is None
                        or not _is_nonempty_string(summary)
                    ):
                        _diag(
                            diagnostics,
                            "DESC013",
                            f"{location}.{locale}",
                            "locale keys and summaries must be non-empty and valid",
                            configuration=True,
                        )
                if diagram_language is not None and not _is_nonempty_string(
                    summaries.get(str(diagram_language))
                ):
                    _diag(
                        diagnostics,
                        "DESC013",
                        f"{location}.{diagram_language}",
                        "must provide the exact project.diagram_language summary",
                        configuration=True,
                    )
            elif diagram_language is not None:
                _diag(
                    diagnostics,
                    "DESC013",
                    f"{location}.{diagram_language}",
                    "must provide the exact project.diagram_language summary",
                    configuration=True,
                )
    elif diagram_language is not None or any(
        isinstance(module.get("description"), dict)
        and "diagram_summaries" in module["description"]
        for module in modules.values()
    ):
        _diag(
            diagnostics,
            "DESC013",
            "project.diagram_language",
            "localized diagram summaries require exact schema 2.2.0",
            configuration=True,
        )
    source_sets = {
        str(item.get("id")): item
        for item in data.get("source_sets", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    composition_roots = _index(
        _list(
            data.get("composition_roots"),
            diagnostics,
            "CMP001",
            "composition_roots",
        ),
        diagnostics,
        "CMP001",
        "composition_roots",
    )
    if not composition_roots:
        _diag(
            diagnostics,
            "CMP001",
            "composition_roots",
            "at least one composition root is required",
            configuration=True,
        )
    release_roots = 0
    for root_id, root in composition_roots.items():
        module_id = root.get("module")
        source_set_id = root.get("source_set")
        path = str(root.get("path", "")).replace("\\", "/")
        if root.get("kind") not in {"release", "validation", "test"}:
            _diag(
                diagnostics,
                "CMP002",
                f"{root_id}.kind",
                "must be release, validation, or test",
                configuration=True,
            )
        if root.get("kind") == "release":
            release_roots += 1
        if module_id not in modules or modules.get(module_id, {}).get("role") != "composition":
            _diag(
                diagnostics,
                "CMP003",
                f"{root_id}.module",
                "composition root must be owned by an L0 composition module",
            )
        if source_set_id not in source_sets:
            _diag(
                diagnostics,
                "CMP004",
                f"{root_id}.source_set",
                "composition root must reference a declared source set",
                configuration=True,
            )
        elif (
            root.get("kind") == "release"
            and source_sets[source_set_id].get("classification") != "production"
        ):
            _diag(
                diagnostics,
                "CMP004",
                f"{root_id}.source_set",
                "release composition root must belong to production",
            )
        if not all(
            _is_nonempty_string(root.get(field))
            for field in ("path", "symbol", "purpose")
        ):
            _diag(
                diagnostics,
                "CMP005",
                root_id,
                "path, symbol, and purpose are required",
                configuration=True,
            )
        module_paths = [
            str(item).replace("\\", "/").rstrip("/")
            for item in modules.get(str(module_id), {}).get("paths", [])
        ]
        if module_paths and not any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in module_paths
        ):
            _diag(
                diagnostics,
                "CMP006",
                f"{root_id}.path",
                "composition root path must be owned by its declared module",
            )
    if release_roots != 1:
        _diag(
            diagnostics,
            "CMP007",
            "composition_roots",
            "exactly one release composition root is required",
            configuration=True,
        )
    python_config = data.get("python_analyzer")
    if not isinstance(python_config, dict) or python_config.get("status") not in {
        "required",
        "not-applicable",
    }:
        _diag(
            diagnostics,
            "PYAST001",
            "python_analyzer",
            "must declare required or not-applicable",
            configuration=True,
        )
    elif not _is_nonempty_string(python_config.get("rationale")):
        _diag(
            diagnostics,
            "PYAST001",
            "python_analyzer.rationale",
            "analyzer applicability requires a rationale",
            configuration=True,
        )
    if "rtos_design_studies" in data:
        _diag(
            diagnostics,
            "SCHED000",
            "rtos_design_studies",
            "obsolete pre-release field; use realtime_scheduling_studies",
            configuration=True,
        )

    flows = {
        str(item.get("id")): item
        for item in data.get("flows", [])
        if isinstance(item, dict) and _is_nonempty_string(item.get("id"))
    }
    step_ids: dict[str, tuple[str, dict[str, Any]]] = {}
    for flow_id, flow in flows.items():
        for index, step in enumerate(flow.get("steps", [])):
            location = f"{flow_id}.steps[{index}]"
            step_id = step.get("id") if isinstance(step, dict) else None
            if not _is_nonempty_string(step_id) or not ID_PATTERN.fullmatch(str(step_id)):
                _diag(diagnostics, "EXE001", f"{location}.id", "schema 2.1.0/2.2.0 requires a stable step ID", configuration=True)
            elif str(step_id) in step_ids:
                _diag(diagnostics, "EXE002", f"{location}.id", f"duplicate flow step ID {step_id!r}", configuration=True)
            else:
                step_ids[str(step_id)] = (flow_id, step)

    workloads = _index(_list(data.get("workloads"), diagnostics, "EXE003", "workloads"), diagnostics, "EXE003", "workloads")
    profiles = _index(_list(data.get("execution_profiles"), diagnostics, "EXE004", "execution_profiles"), diagnostics, "EXE004", "execution_profiles")
    units = _index(_list(data.get("execution_units"), diagnostics, "EXE005", "execution_units"), diagnostics, "EXE005", "execution_units")
    mappings = _index(_list(data.get("execution_mappings"), diagnostics, "EXE006", "execution_mappings"), diagnostics, "EXE006", "execution_mappings")
    channels = _index(_list(data.get("execution_channels"), diagnostics, "EXE007", "execution_channels"), diagnostics, "EXE007", "execution_channels")
    data_profiles = _index(_list(data.get("data_access_profiles"), diagnostics, "PERF001", "data_access_profiles"), diagnostics, "PERF001", "data_access_profiles")
    micro_profiles = _index(_list(data.get("microarchitecture_profiles"), diagnostics, "PERF002", "microarchitecture_profiles"), diagnostics, "PERF002", "microarchitecture_profiles")
    variants = _index(_list(data.get("platform_variants"), diagnostics, "EXE008", "platform_variants"), diagnostics, "EXE008", "platform_variants")
    validation_profiles = _index(
        _list(
            data.get("validation_profiles"),
            diagnostics,
            "VAL003",
            "validation_profiles",
        ),
        diagnostics,
        "VAL003",
        "validation_profiles",
    )
    studies = _index(
        _list(
            data.get("realtime_scheduling_studies"),
            diagnostics,
            "SCHED001",
            "realtime_scheduling_studies",
        ),
        diagnostics,
        "SCHED001",
        "realtime_scheduling_studies",
    )
    realtime_workloads = {
        workload_id
        for workload_id, workload in workloads.items()
        if workload.get("timing_class") in {"hard-real-time", "soft-real-time"}
    }
    realtime_pairs = {
        (str(mapping.get("workload")), str(mapping.get("profile")))
        for mapping in mappings.values()
        if mapping.get("workload") in realtime_workloads
        and mapping.get("profile") in profiles
    }
    realtime_profiles = {
        profile_id for _, profile_id in realtime_pairs
    }

    for workload_id, workload in workloads.items():
        flow_id = workload.get("flow")
        if flow_id not in flows:
            _diag(diagnostics, "EXE010", f"{workload_id}.flow", f"unknown Flow {flow_id!r}")
        referenced_steps = _refs(workload.get("steps"), step_ids, diagnostics, "EXE011", f"{workload_id}.steps", required=True)
        for step_id in referenced_steps:
            if flow_id in flows and step_ids[step_id][0] != flow_id:
                _diag(diagnostics, "EXE012", f"{workload_id}.steps", f"step {step_id!r} belongs to another Flow")
        timing_class = workload.get("timing_class")
        if timing_class not in TIMING_CLASSES:
            _diag(diagnostics, "EXE013", f"{workload_id}.timing_class", f"must be one of {sorted(TIMING_CLASSES)}", configuration=True)
        _mapping(workload.get("activation"), diagnostics, "EXE014", f"{workload_id}.activation")
        _mapping(workload.get("data"), diagnostics, "EXE015", f"{workload_id}.data")
        budgets = _list(workload.get("budgets"), diagnostics, "PERF003", f"{workload_id}.budgets")
        for index, raw in enumerate(budgets):
            budget = _mapping(raw, diagnostics, "PERF003", f"{workload_id}.budgets[{index}]")
            for key in ("metric", "operator", "threshold", "unit", "method"):
                if not _is_nonempty_string(budget.get(key)) and not (key == "threshold" and isinstance(budget.get(key), (int, float))):
                    _diag(diagnostics, "PERF003", f"{workload_id}.budgets[{index}].{key}", "is required", configuration=True)
        if timing_class == "hard-real-time":
            if not _has_metric(workload, "deadline") or not _has_metric(workload, "deadline-miss-count"):
                _diag(diagnostics, "PERF004", workload_id, "hard-real-time workload requires deadline and deadline-miss-count budgets")
            analysis = _mapping(workload.get("tier1_analysis"), diagnostics, "PERF005", f"{workload_id}.tier1_analysis")
            for field in sorted(REQUIRED_TIER1_FIELDS):
                if not _is_nonempty_string(analysis.get(field)):
                    _diag(diagnostics, "PERF005", f"{workload_id}.tier1_analysis.{field}", "hard-real-time analysis is required")
        if timing_class == "soft-real-time":
            has_percentile = any(
                isinstance(item, dict) and item.get("method") == "percentile"
                for item in workload.get("budgets", [])
            )
            if not has_percentile or not _has_metric(workload, "deadline-miss-rate"):
                _diag(diagnostics, "PERF006", workload_id, "soft-real-time workload requires percentile and deadline-miss-rate budgets")

    covered_flows = {str(item.get("flow")) for item in workloads.values()}
    for flow_id in flows:
        if flow_id not in covered_flows:
            _diag(diagnostics, "EXE016", flow_id, "schema 1.2 requires at least one workload for every Flow")

    for profile_id, profile in profiles.items():
        status = profile.get("status")
        if status not in PROFILE_STATUSES:
            _diag(diagnostics, "EXE020", f"{profile_id}.status", f"must be one of {sorted(PROFILE_STATUSES)}", configuration=True)
        assurance_scope = profile.get("assurance_scope")
        if (
            not isinstance(assurance_scope, list)
            or not assurance_scope
            or any(item not in ASSURANCE_SCOPES for item in assurance_scope)
            or len(set(assurance_scope)) != len(assurance_scope)
        ):
            _diag(
                diagnostics,
                "EXE027",
                f"{profile_id}.assurance_scope",
                f"must be a unique non-empty list from {sorted(ASSURANCE_SCOPES)}",
                configuration=True,
            )
        target = _mapping(profile.get("target"), diagnostics, "EXE021", f"{profile_id}.target")
        if status == "accepted":
            for field in REQUIRED_ACCEPTED_TARGET_FIELDS:
                if not _is_nonempty_string(target.get(field)) or "TODO" in str(target.get(field)).upper():
                    _diag(diagnostics, "EXE022", f"{profile_id}.target.{field}", "accepted profile requires a confirmed value")
            if not isinstance(target.get("cache_topology"), dict) or not target.get("cache_topology"):
                _diag(diagnostics, "EXE023", f"{profile_id}.target.cache_topology", "accepted profile requires confirmed cache topology")
            if not isinstance(target.get("scheduler_capabilities"), list) or not target.get("scheduler_capabilities"):
                _diag(diagnostics, "EXE024", f"{profile_id}.target.scheduler_capabilities", "accepted profile requires scheduler capabilities")
            if not _valid_human_approval(profile.get("approval")):
                _diag(diagnostics, "EXE025", f"{profile_id}.approval", "accepted profile requires non-AI human approval metadata")
        if profile.get("execution_model") not in {
            None,
            "rtos",
            "os",
            "event-loop",
            "bare-metal",
        }:
            _diag(
                diagnostics,
                "EXE026",
                f"{profile_id}.execution_model",
                "must be rtos, os, event-loop, or bare-metal",
                configuration=True,
            )
        if profile_id in realtime_profiles and profile.get(
            "execution_model"
        ) not in {"rtos", "os", "bare-metal"}:
            _diag(
                diagnostics,
                "SCHED005",
                f"{profile_id}.execution_model",
                "real-time profile must explicitly select rtos, os, or bare-metal",
                configuration=True,
            )
        if profile_id in realtime_profiles and "real-time" not in (
            assurance_scope if isinstance(assurance_scope, list) else []
        ):
            _diag(
                diagnostics,
                "SCHED006",
                f"{profile_id}.assurance_scope",
                "real-time workload mapping requires real-time assurance scope",
            )
        if isinstance(profile.get("overheads"), dict) and "timer_isr_ns" in profile[
            "overheads"
        ]:
            _diag(
                diagnostics,
                "SCHED000",
                f"{profile_id}.overheads.timer_isr_ns",
                "obsolete pre-release field; use timer_interrupt_ns",
                configuration=True,
            )

    for validation_id, validation_profile in validation_profiles.items():
        if validation_profile.get("applicability") not in {
            "required",
            "not-applicable",
        }:
            _diag(
                diagnostics,
                "VAL003",
                f"{validation_id}.applicability",
                "must be required or not-applicable",
                configuration=True,
            )
        if not _is_nonempty_string(validation_profile.get("rationale")):
            _diag(
                diagnostics,
                "VAL003",
                f"{validation_id}.rationale",
                "validation applicability requires a rationale",
                configuration=True,
            )

    for unit_id, unit in units.items():
        profile_id = unit.get("profile")
        if profile_id not in profiles:
            _diag(diagnostics, "EXE030", f"{unit_id}.profile", f"unknown execution profile {profile_id!r}")
        if unit.get("kind") not in UNIT_KINDS:
            _diag(diagnostics, "EXE031", f"{unit_id}.kind", f"must be one of {sorted(UNIT_KINDS)}", configuration=True)
        if not isinstance(unit.get("concurrency"), int) or unit.get("concurrency", 0) <= 0:
            _diag(diagnostics, "EXE032", f"{unit_id}.concurrency", "must be a positive integer", configuration=True)
        for field in ("priority", "affinity", "resources", "blocking", "allocation"):
            if field not in unit:
                _diag(diagnostics, "EXE033", f"{unit_id}.{field}", "must be declared explicitly", configuration=True)
        for obsolete in ("rtos", "rtos_isr"):
            if obsolete in unit:
                _diag(
                    diagnostics,
                    "SCHED000",
                    f"{unit_id}.{obsolete}",
                    "obsolete pre-release field; use realtime_task or interrupt_interference",
                    configuration=True,
                )
        if profile_id in realtime_profiles:
            if unit.get("kind") not in {"dedicated-task", "interrupt"}:
                _diag(
                    diagnostics,
                    "SCHED020",
                    unit_id,
                    "rate-monotonic analysis requires dedicated-task or interrupt units",
                )
            if unit.get("kind") == "dedicated-task" and not isinstance(
                unit.get("realtime_task"), dict
            ):
                _diag(
                    diagnostics,
                    "SCHED021",
                    f"{unit_id}.realtime_task",
                    "dedicated analyzed task requires a real-time task model",
                    configuration=True,
                )
            if unit.get("kind") == "interrupt" and not isinstance(
                unit.get("interrupt_interference"), dict
            ):
                _diag(
                    diagnostics,
                    "SCHED022",
                    f"{unit_id}.interrupt_interference",
                    "interrupt requires WCET, arrival, jitter, and core bounds",
                    configuration=True,
                )

    for mapping_id, mapping in mappings.items():
        profile_id = mapping.get("profile")
        workload_id = mapping.get("workload")
        if profile_id not in profiles:
            _diag(diagnostics, "EXE040", f"{mapping_id}.profile", f"unknown execution profile {profile_id!r}")
        if workload_id not in workloads:
            _diag(diagnostics, "EXE041", f"{mapping_id}.workload", f"unknown workload {workload_id!r}")
        mapped_units = _refs(mapping.get("units"), units, diagnostics, "EXE042", f"{mapping_id}.units", required=True)
        mapped_steps = _refs(mapping.get("steps"), step_ids, diagnostics, "EXE043", f"{mapping_id}.steps", required=True)
        if workload_id in workloads:
            allowed_steps = set(workloads[workload_id].get("steps", []))
            for step_id in mapped_steps:
                if step_id not in allowed_steps:
                    _diag(diagnostics, "EXE044", f"{mapping_id}.steps", f"step {step_id!r} is outside workload {workload_id!r}")
        for unit_id in mapped_units:
            if profile_id in profiles and units[unit_id].get("profile") != profile_id:
                _diag(diagnostics, "EXE045", f"{mapping_id}.units", f"unit {unit_id!r} belongs to another profile")
        for field in ("serialization", "reentrant", "activation", "wcet"):
            if field not in mapping:
                _diag(diagnostics, "EXE046", f"{mapping_id}.{field}", "must be declared explicitly", configuration=True)

    ports = {str(item.get("id")): item for item in data.get("ports", []) if isinstance(item, dict)}
    events = {str(item.get("id")): item for item in data.get("events", []) if isinstance(item, dict)}
    contract_refs = {**ports, **events}
    for channel_id, channel in channels.items():
        profile_id = channel.get("profile")
        if profile_id not in profiles:
            _diag(diagnostics, "EXE050", f"{channel_id}.profile", f"unknown execution profile {profile_id!r}")
        for field in ("from_unit", "to_unit"):
            unit_id = channel.get(field)
            if unit_id not in units:
                _diag(diagnostics, "EXE051", f"{channel_id}.{field}", f"unknown unit {unit_id!r}")
            elif profile_id in profiles and units[unit_id].get("profile") != profile_id:
                _diag(diagnostics, "EXE052", f"{channel_id}.{field}", "unit belongs to another profile")
        _refs(channel.get("contract_refs"), contract_refs, diagnostics, "EXE053", f"{channel_id}.contract_refs", required=True)
        if not isinstance(channel.get("capacity"), int) or channel.get("capacity", -1) < 0:
            _diag(diagnostics, "EXE054", f"{channel_id}.capacity", "must be a non-negative integer", configuration=True)
        for field in ("ordering", "copy_policy", "timeout_ms"):
            if field not in channel:
                _diag(diagnostics, "EXE055", f"{channel_id}.{field}", "must be declared explicitly", configuration=True)
        if not isinstance(channel.get("timeout_ms"), (int, float)) or isinstance(channel.get("timeout_ms"), bool) or channel.get("timeout_ms", -1) < 0:
            _diag(diagnostics, "EXE057", f"{channel_id}.timeout_ms", "must be a non-negative number", configuration=True)
        if channel.get("overload") not in OVERLOAD_POLICIES:
            _diag(diagnostics, "EXE056", f"{channel_id}.overload", f"must be one of {sorted(OVERLOAD_POLICIES)}")
        if "rtos_timing" in channel:
            _diag(
                diagnostics,
                "SCHED000",
                f"{channel_id}.rtos_timing",
                "obsolete pre-release field; use realtime_timing",
                configuration=True,
            )
        if profile_id in realtime_profiles and not isinstance(
            channel.get("realtime_timing"), dict
        ):
            _diag(
                diagnostics,
                "SCHED030",
                f"{channel_id}.realtime_timing",
                "analyzed channel requires timing and CPU-cost accounting",
                configuration=True,
            )

    for profile_id in realtime_profiles:
        profile = profiles[profile_id]
        if profile.get("analysis_phase") not in {"provisional", "final"}:
            _diag(
                diagnostics,
                "SCHED010",
                f"{profile_id}.analysis_phase",
                "must be provisional or final",
                configuration=True,
            )
        if profile.get("status") == "accepted" and profile.get(
            "analysis_phase"
        ) != "final":
            _diag(
                diagnostics,
                "SCHED011",
                profile_id,
                "accepted real-time profile requires final analysis",
            )

    pair_coverage: dict[tuple[str, str], list[str]] = {}
    for study_id, study in studies.items():
        analysis_method = study.get("analysis_method")
        if not _is_nonempty_string(analysis_method):
            _diag(
                diagnostics,
                "SCHED040",
                f"{study_id}.analysis_method",
                "is required",
                configuration=True,
            )
        candidate_profiles = _refs(
            study.get("candidate_profiles"),
            profiles,
            diagnostics,
            "SCHED040",
            f"{study_id}.candidate_profiles",
            required=True,
        )
        if len(candidate_profiles) < 2:
            _diag(diagnostics, "SCHED041", f"{study_id}.candidate_profiles", "must contain at least two candidates", configuration=True)
        if len(candidate_profiles) != len(set(candidate_profiles)):
            _diag(diagnostics, "SCHED041", f"{study_id}.candidate_profiles", "must not contain duplicates", configuration=True)
        selected_profile = study.get("selected_profile")
        if selected_profile not in candidate_profiles:
            _diag(diagnostics, "SCHED043", f"{study_id}.selected_profile", "must select exactly one candidate profile", configuration=True)
        workload_refs = _refs(
            study.get("workload_refs"),
            workloads,
            diagnostics,
            "SCHED044",
            f"{study_id}.workload_refs",
            required=True,
        )
        if any(workload_id not in realtime_workloads for workload_id in workload_refs):
            _diag(
                diagnostics,
                "SCHED044",
                f"{study_id}.workload_refs",
                "must contain only hard-real-time or soft-real-time workloads",
            )
        flow_refs = _refs(study.get("flow_refs"), flows, diagnostics, "SCHED044", f"{study_id}.flow_refs", required=True)
        expected_flows = {
            str(workloads[workload_id].get("flow"))
            for workload_id in workload_refs
            if workload_id in workloads
        }
        if set(flow_refs) != expected_flows:
            _diag(
                diagnostics,
                "SCHED044",
                f"{study_id}.flow_refs",
                "must exactly match the Flows owned by workload_refs",
            )
        if not _is_nonempty_string(study.get("objective")):
            _diag(diagnostics, "SCHED044", f"{study_id}.objective", "must state the scheduling objective")
        for field in ("requirements", "assumptions"):
            values = _nonempty_list(
                study.get(field), diagnostics, "SCHED044", f"{study_id}.{field}"
            )
            for index, value in enumerate(values):
                if not _is_nonempty_string(value):
                    _diag(
                        diagnostics,
                        "SCHED044",
                        f"{study_id}.{field}[{index}]",
                        "must be a non-empty string",
                        configuration=True,
                    )
        if not _is_nonempty_string(study.get("selection_rationale")):
            _diag(diagnostics, "SCHED045", f"{study_id}.selection_rationale", "must explain task count, frequency, overhead, synchronization, jitter, and core tradeoffs")
        if not _valid_human_approval(study.get("selection_approval")):
            _diag(diagnostics, "SCHED046", f"{study_id}.selection_approval", "requires non-AI human selection approval")
        study_phase = study.get("analysis_phase")
        if study_phase not in {"provisional", "final"}:
            _diag(diagnostics, "SCHED047", f"{study_id}.analysis_phase", "must be provisional or final", configuration=True)
        flow_chains = _list(study.get("flow_chains"), diagnostics, "SCHED048", f"{study_id}.flow_chains")
        if not isinstance(study.get("candidate_outcomes"), dict):
            _diag(diagnostics, "SCHED048", f"{study_id}.candidate_outcomes", "must be a mapping", configuration=True)
        if not isinstance(study.get("rejection_reasons"), dict):
            _diag(diagnostics, "SCHED048", f"{study_id}.rejection_reasons", "must be a mapping", configuration=True)
        chain_profiles = {
            str(chain.get("profile"))
            for chain in flow_chains
            if isinstance(chain, dict)
        }
        for profile_id in candidate_profiles:
            if profile_id not in chain_profiles:
                _diag(diagnostics, "SCHED049", study_id, f"candidate {profile_id!r} requires at least one Flow chain")
            mapped_workloads = {
                str(mapping.get("workload"))
                for mapping in mappings.values()
                if mapping.get("profile") == profile_id
            }
            if not set(workload_refs).issubset(mapped_workloads):
                _diag(
                    diagnostics,
                    "SCHED042",
                    profile_id,
                    "every candidate must map every study workload",
                )
            for workload_id in workload_refs:
                if (workload_id, profile_id) in realtime_pairs:
                    pair_coverage.setdefault((workload_id, profile_id), []).append(
                        study_id
                    )
            candidate_chain_flows = {
                str(chain.get("flow"))
                for chain in flow_chains
                if isinstance(chain, dict) and chain.get("profile") == profile_id
            }
            if not set(flow_refs).issubset(candidate_chain_flows):
                _diag(
                    diagnostics,
                    "SCHED057",
                    profile_id,
                    "every governed Flow requires a chain for this candidate",
                )
            if profiles.get(profile_id, {}).get("analysis_phase") != study_phase:
                _diag(diagnostics, "SCHED050", profile_id, "profile and scheduling-study analysis phases must match")

        analysis_results: dict[str, dict[str, Any]] = {}
        fingerprints: list[tuple[Any, ...]] = []
        for profile_id in candidate_profiles:
            if profile_id not in profiles:
                continue
            result = analyze_realtime_profile(
                profiles[profile_id],
                units,
                mappings,
                channels,
                workloads,
                flow_chains,
                analysis_method=str(analysis_method),
            )
            analysis_results[profile_id] = result
            fingerprints.append(result["fingerprint"])
            for problem in result["problems"]:
                _diag(diagnostics, "SCHED060", profile_id, problem, configuration=True)
            if profile_id == selected_profile:
                for failure in result["failures"]:
                    _diag(diagnostics, "SCHED061", profile_id, failure)
                if result["verdict"] != "PASS":
                    _diag(diagnostics, "SCHED062", profile_id, "selected candidate must have a complete scheduling-analysis PASS")
        if len(set(fingerprints)) != len(fingerprints):
            _diag(diagnostics, "SCHED051", study_id, "candidate profiles must be structurally distinct")

        soft_workload_refs = {
            workload_id
            for workload_id in workload_refs
            if workloads.get(workload_id, {}).get("timing_class")
            == "soft-real-time"
        }
        soft_plans = _list(
            study.get("soft_acceptance_plans", []),
            diagnostics,
            "SCHED063",
            f"{study_id}.soft_acceptance_plans",
        )
        planned_soft_workloads: set[str] = set()
        for index, raw in enumerate(soft_plans):
            plan = _mapping(
                raw,
                diagnostics,
                "SCHED063",
                f"{study_id}.soft_acceptance_plans[{index}]",
            )
            workload_id = plan.get("workload")
            if workload_id not in soft_workload_refs:
                _diag(
                    diagnostics,
                    "SCHED063",
                    f"{study_id}.soft_acceptance_plans[{index}].workload",
                    "must reference a soft-real-time study workload",
                )
            else:
                planned_soft_workloads.add(str(workload_id))
            for field in ("validation_plan_path", "evidence_format"):
                if not _is_nonempty_string(plan.get(field)):
                    _diag(
                        diagnostics,
                        "SCHED063",
                        f"{study_id}.soft_acceptance_plans[{index}].{field}",
                        "is required",
                        configuration=True,
                    )
            if not _valid_human_approval(plan.get("risk_approval")):
                _diag(
                    diagnostics,
                    "SCHED063",
                    f"{study_id}.soft_acceptance_plans[{index}].risk_approval",
                    "requires non-AI risk acceptance",
                )
        if not soft_workload_refs.issubset(planned_soft_workloads):
            _diag(
                diagnostics,
                "SCHED063",
                study_id,
                "every soft-real-time workload requires an SLO validation plan and non-AI risk acceptance",
            )

        if selected_profile in profiles and profiles[selected_profile].get("status") == "accepted":
            if study_phase != "final":
                _diag(diagnostics, "SCHED052", study_id, "accepted selected profile requires final scheduling study")
            if not _valid_human_approval(study.get("final_approval")):
                _diag(diagnostics, "SCHED053", f"{study_id}.final_approval", "accepted selected profile requires final non-AI approval")
            runtime_evidence = _nonempty_list(
                profiles[selected_profile].get("runtime_evidence"),
                diagnostics,
                "SCHED013",
                f"{selected_profile}.runtime_evidence",
            )
            for index, raw in enumerate(runtime_evidence):
                evidence = _mapping(
                    raw,
                    diagnostics,
                    "SCHED013",
                    f"{selected_profile}.runtime_evidence[{index}]",
                )
                for field in ("path", "sha256", "profile_id", "manifest_sha256"):
                    if not _is_nonempty_string(evidence.get(field)):
                        _diag(
                            diagnostics,
                            "SCHED013",
                            f"{selected_profile}.runtime_evidence[{index}].{field}",
                            "is required",
                            configuration=True,
                        )
                if evidence.get("profile_id") != selected_profile:
                    _diag(
                        diagnostics,
                        "SCHED014",
                        f"{selected_profile}.runtime_evidence[{index}].profile_id",
                        "must bind the selected execution profile",
                    )
                for field in ("sha256", "manifest_sha256"):
                    if _is_nonempty_string(evidence.get(field)) and not re.fullmatch(
                        r"[0-9a-fA-F]{64}", str(evidence.get(field))
                    ):
                        _diag(
                            diagnostics,
                            "SCHED015",
                            f"{selected_profile}.runtime_evidence[{index}].{field}",
                            "must be a 64-character SHA-256",
                            configuration=True,
                        )

            slo_results = _list(
                study.get("soft_slo_results", []),
                diagnostics,
                "SCHED064",
                f"{study_id}.soft_slo_results",
            )
            passing_slo_workloads: set[str] = set()
            for index, raw in enumerate(slo_results):
                slo = _mapping(
                    raw,
                    diagnostics,
                    "SCHED064",
                    f"{study_id}.soft_slo_results[{index}]",
                )
                workload_id = slo.get("workload")
                if workload_id not in soft_workload_refs:
                    _diag(
                        diagnostics,
                        "SCHED064",
                        f"{study_id}.soft_slo_results[{index}].workload",
                        "must reference a soft-real-time study workload",
                    )
                if slo.get("verdict") == "pass" and workload_id in soft_workload_refs:
                    passing_slo_workloads.add(str(workload_id))
                elif slo.get("verdict") != "pass":
                    _diag(
                        diagnostics,
                        "SCHED064",
                        f"{study_id}.soft_slo_results[{index}].verdict",
                        "final soft SLO verdict must be pass",
                    )
                for field in (
                    "evidence_path",
                    "evidence_sha256",
                    "profile_id",
                    "manifest_sha256",
                ):
                    if not _is_nonempty_string(slo.get(field)):
                        _diag(
                            diagnostics,
                            "SCHED064",
                            f"{study_id}.soft_slo_results[{index}].{field}",
                            "is required",
                            configuration=True,
                        )
                if slo.get("profile_id") != selected_profile:
                    _diag(
                        diagnostics,
                        "SCHED064",
                        f"{study_id}.soft_slo_results[{index}].profile_id",
                        "must bind the selected execution profile",
                    )
                for field in ("evidence_sha256", "manifest_sha256"):
                    if _is_nonempty_string(slo.get(field)) and not re.fullmatch(
                        r"[0-9a-fA-F]{64}", str(slo.get(field))
                    ):
                        _diag(
                            diagnostics,
                            "SCHED064",
                            f"{study_id}.soft_slo_results[{index}].{field}",
                            "must be a 64-character SHA-256",
                            configuration=True,
                        )
            if passing_slo_workloads != soft_workload_refs:
                _diag(
                    diagnostics,
                    "SCHED064",
                    study_id,
                    "accepted profile requires PASS SLO evidence for every soft workload",
                )

        for profile_id, result in analysis_results.items():
            declared = study.get("candidate_outcomes", {}).get(profile_id) if isinstance(study.get("candidate_outcomes"), dict) else None
            if profile_id != selected_profile and declared not in {"pass", "pass-with-soft-risk", "rejected"}:
                _diag(diagnostics, "SCHED054", f"{study_id}.candidate_outcomes.{profile_id}", "unselected candidate outcome must be pass, pass-with-soft-risk, or rejected")
            if declared == "pass" and (
                result["verdict"] != "PASS" or result.get("soft_risks")
            ):
                _diag(diagnostics, "SCHED055", profile_id, "candidate declared pass but analysis did not pass without risk")
            if declared == "pass-with-soft-risk" and (
                result["verdict"] != "PASS" or not result.get("soft_risks")
            ):
                _diag(diagnostics, "SCHED055", profile_id, "candidate risk outcome does not match analysis")
            if declared == "rejected" and not _is_nonempty_string(study.get("rejection_reasons", {}).get(profile_id) if isinstance(study.get("rejection_reasons"), dict) else None):
                _diag(diagnostics, "SCHED056", f"{study_id}.rejection_reasons.{profile_id}", "rejected candidate requires a reason")

    for pair in sorted(realtime_pairs):
        coverage = pair_coverage.get(pair, [])
        if len(coverage) != 1:
            _diag(
                diagnostics,
                "SCHED070",
                f"{pair[0]}:{pair[1]}",
                "every real-time workload/profile mapping must belong to exactly one scheduling study",
            )

    for data_id, profile in data_profiles.items():
        if profile.get("profile") not in profiles:
            _diag(diagnostics, "PERF010", f"{data_id}.profile", "unknown execution profile")
        if profile.get("workload") not in workloads:
            _diag(diagnostics, "PERF011", f"{data_id}.workload", "unknown workload")
        if profile.get("tier") not in OPTIMIZATION_TIERS:
            _diag(diagnostics, "PERF012", f"{data_id}.tier", f"must be one of {sorted(OPTIMIZATION_TIERS)}")
        for field in (
            "element_size_bytes",
            "layout",
            "active_working_set_bytes",
            "stride_bytes",
            "reuse",
            "alignment_bytes",
            "sharing",
            "cache_target",
            "candidates",
        ):
            if field not in profile:
                _diag(diagnostics, "PERF013", f"{data_id}.{field}", "must be declared explicitly", configuration=True)
        for field in ("element_size_bytes", "active_working_set_bytes", "stride_bytes", "alignment_bytes"):
            if not isinstance(profile.get(field), int) or isinstance(profile.get(field), bool) or profile.get(field, 0) <= 0:
                _diag(diagnostics, "PERF015", f"{data_id}.{field}", "must be a positive integer", configuration=True)
        if not isinstance(profile.get("candidates"), list) or not profile.get("candidates"):
            _diag(diagnostics, "PERF016", f"{data_id}.candidates", "must be a non-empty list", configuration=True)
        if profile.get("tier") == "tier-2" and (not profile.get("portable_baseline") or not profile.get("benchmark")):
            _diag(diagnostics, "PERF014", data_id, "tier-2 data optimization requires portable_baseline and benchmark")

    for micro_id, profile in micro_profiles.items():
        if profile.get("profile") not in profiles:
            _diag(diagnostics, "PERF020", f"{micro_id}.profile", "unknown execution profile")
        if profile.get("workload") not in workloads:
            _diag(diagnostics, "PERF021", f"{micro_id}.workload", "unknown workload")
        if profile.get("tier") not in OPTIMIZATION_TIERS:
            _diag(diagnostics, "PERF022", f"{micro_id}.tier", f"must be one of {sorted(OPTIMIZATION_TIERS)}")
        for field in ("branches", "simd_eligibility", "compiler", "compiler_flags", "vectorization_report", "pgo", "lto"):
            if field not in profile:
                _diag(diagnostics, "PERF023", f"{micro_id}.{field}", "must be declared explicitly", configuration=True)
        if profile.get("tier") == "tier-2" and (not profile.get("portable_baseline") or not profile.get("benchmark")):
            _diag(diagnostics, "PERF024", micro_id, "tier-2 microarchitecture optimization requires portable_baseline and benchmark")

    for variant_id, variant in variants.items():
        profile_id = variant.get("profile")
        if profile_id not in profiles:
            _diag(diagnostics, "EXE060", f"{variant_id}.profile", "unknown execution profile")
        _refs(variant.get("units"), units, diagnostics, "EXE061", f"{variant_id}.units")
        _refs(variant.get("data_access_profiles"), data_profiles, diagnostics, "EXE062", f"{variant_id}.data_access_profiles")
        _refs(variant.get("microarchitecture_profiles"), micro_profiles, diagnostics, "EXE063", f"{variant_id}.microarchitecture_profiles")
        if not isinstance(variant.get("parameters"), dict):
            _diag(diagnostics, "EXE064", f"{variant_id}.parameters", "must be a mapping", configuration=True)
        if variant.get("release") is True and (profile_id not in profiles or profiles[profile_id].get("status") != "accepted"):
            _diag(diagnostics, "EXE065", variant_id, "release variant must reference an accepted execution profile")

    if check_docs:
        from render_architecture import compare_documents

        for rule_id, location, message in compare_documents(data, manifest_path):
            _diag(diagnostics, rule_id, location, message)

    _apply_governance(diagnostics, data, manifest_path, baseline_path, previous_baseline_path)
    return diagnostics
