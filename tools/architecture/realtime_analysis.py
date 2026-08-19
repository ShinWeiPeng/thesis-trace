"""Deterministic real-time scheduling analysis with an RM/RTA implementation."""

from __future__ import annotations

from fractions import Fraction
from math import ceil
import re
from typing import Any

TIMING_CLASS_RANK = {
    "best-effort": 0,
    "soft-real-time": 1,
    "hard-real-time": 2,
}
SUPPORTED_ANALYSIS_METHOD = "rate-monotonic-rta"


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _effective_period(task: dict[str, Any]) -> int | None:
    activation = task.get("activation")
    if not isinstance(activation, dict):
        return None
    kind = activation.get("kind")
    if kind == "periodic":
        value = activation.get("period_ns")
    elif kind == "sporadic":
        value = activation.get("minimum_interarrival_ns")
    elif kind == "server":
        value = activation.get("replenishment_period_ns")
    else:
        return None
    return value if _positive_int(value) else None


def _component_cost(
    component: dict[str, Any], phase: str, problems: list[str], location: str
) -> int:
    if phase == "final":
        value = component.get("final_ns")
        basis = component.get("basis")
        if basis not in {"measured", "static-analysis"}:
            problems.append(f"{location}.basis must be measured or static-analysis")
        if not isinstance(component.get("evidence_path"), str) or not component.get(
            "evidence_path"
        ):
            problems.append(f"{location}.evidence_path is required for final analysis")
        digest = component.get("evidence_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            problems.append(
                f"{location}.evidence_sha256 must be a 64-character SHA-256"
            )
    else:
        value = component.get("budget_ns")
    if not _positive_int(value):
        problems.append(
            f"{location}.{'final_ns' if phase == 'final' else 'budget_ns'} "
            "must be a positive integer"
        )
        return 0
    return value


def _task_cost(
    unit: dict[str, Any],
    profile: dict[str, Any],
    channel_costs: dict[str, int],
    problems: list[str],
) -> int:
    task_id = str(unit.get("id"))
    task = unit.get("realtime_task")
    if not isinstance(task, dict):
        problems.append(f"{task_id}.realtime_task must be a mapping")
        return 0
    phase = str(profile.get("analysis_phase"))
    components = task.get("demand_components")
    if not isinstance(components, list) or not components:
        problems.append(f"{task_id}.realtime_task.demand_components must not be empty")
        components = []
    demand = 0
    seen_mappings: set[str] = set()
    for index, raw in enumerate(components):
        location = f"{task_id}.realtime_task.demand_components[{index}]"
        if not isinstance(raw, dict):
            problems.append(f"{location} must be a mapping")
            continue
        mapping_id = raw.get("mapping")
        if not isinstance(mapping_id, str) or not mapping_id:
            problems.append(f"{location}.mapping is required")
        elif mapping_id in seen_mappings:
            problems.append(f"{location}.mapping duplicates {mapping_id!r}")
        else:
            seen_mappings.add(mapping_id)
        demand += _component_cost(raw, phase, problems, location)

    activation = task.get("activation", {})
    if isinstance(activation, dict) and activation.get("kind") == "server":
        if activation.get("server_type") not in {"sporadic", "deferrable"}:
            problems.append(
                f"{task_id}.realtime_task.activation.server_type must be sporadic or deferrable"
            )
        budget = activation.get("budget_ns")
        if not _positive_int(budget):
            problems.append(
                f"{task_id}.realtime_task.activation.budget_ns must be positive"
            )
        elif demand > budget:
            problems.append(
                f"{task_id} demand {demand}ns exceeds server budget {budget}ns"
            )
        else:
            demand = budget

    overheads = profile.get("overheads")
    if not isinstance(overheads, dict):
        problems.append(f"{profile.get('id')}.overheads must be a mapping")
        overheads = {}
    fixed_overhead = 0
    for field in (
        "context_switch_ns",
        "dispatch_ns",
        "timer_interrupt_ns",
    ):
        value = overheads.get(field)
        if not _nonnegative_int(value):
            problems.append(f"{profile.get('id')}.overheads.{field} must be nonnegative")
        else:
            fixed_overhead += value
    return demand + fixed_overhead + channel_costs.get(task_id, 0)


def _task_fingerprint(
    profile_id: str,
    units: dict[str, dict[str, Any]],
    channels: dict[str, dict[str, Any]],
) -> tuple[Any, ...]:
    task_rows: list[tuple[Any, ...]] = []
    for unit_id, unit in units.items():
        if unit.get("profile") != profile_id or unit.get("kind") != "dedicated-task":
            continue
        task = unit.get("realtime_task", {})
        activation = task.get("activation", {}) if isinstance(task, dict) else {}
        mappings = tuple(
            sorted(
                str(item.get("mapping"))
                for item in task.get("demand_components", [])
                if isinstance(item, dict)
            )
        ) if isinstance(task, dict) else ()
        task_rows.append(
            (
                mappings,
                activation.get("kind"),
                _effective_period(task) if isinstance(task, dict) else None,
                task.get("core") if isinstance(task, dict) else None,
            )
        )
    channel_rows = sorted(
        (
            str(item.get("from_unit")),
            str(item.get("to_unit")),
            bool(item.get("realtime_timing", {}).get("cross_core")),
        )
        for item in channels.values()
        if item.get("profile") == profile_id
        and isinstance(item.get("realtime_timing"), dict)
    )
    return tuple(sorted(task_rows)), tuple(channel_rows)


def _highest_timing_class(values: list[str]) -> str:
    return max(values or ["best-effort"], key=lambda item: TIMING_CLASS_RANK[item])


def _task_timing_class(
    task: dict[str, Any],
    mappings: dict[str, dict[str, Any]],
    workloads: dict[str, dict[str, Any]],
) -> str:
    classes: list[str] = []
    for component in task.get("demand_components", []):
        if not isinstance(component, dict):
            continue
        mapping = mappings.get(str(component.get("mapping")), {})
        workload = workloads.get(str(mapping.get("workload")), {})
        timing_class = workload.get("timing_class")
        if timing_class in TIMING_CLASS_RANK:
            classes.append(str(timing_class))
    return _highest_timing_class(classes)


def _flow_timing_class(
    profile_id: str,
    flow_id: Any,
    mappings: dict[str, dict[str, Any]],
    workloads: dict[str, dict[str, Any]],
) -> str:
    mapped_workloads = {
        str(mapping.get("workload"))
        for mapping in mappings.values()
        if mapping.get("profile") == profile_id
    }
    classes = [
        str(workload.get("timing_class"))
        for workload_id, workload in workloads.items()
        if workload_id in mapped_workloads
        and workload.get("flow") == flow_id
        and workload.get("timing_class") in TIMING_CLASS_RANK
    ]
    return _highest_timing_class(classes)


def analyze_realtime_profile(
    profile: dict[str, Any],
    units: dict[str, dict[str, Any]],
    mappings: dict[str, dict[str, Any]],
    channels: dict[str, dict[str, Any]],
    workloads: dict[str, dict[str, Any]],
    flow_chains: list[dict[str, Any]] | None = None,
    *,
    analysis_method: str = SUPPORTED_ANALYSIS_METHOD,
    max_iterations: int = 10000,
) -> dict[str, Any]:
    """Return deterministic PASS, FAIL, or BLOCKED analysis for one profile."""
    profile_id = str(profile.get("id"))
    problems: list[str] = []
    failures: list[str] = []
    soft_risks: list[str] = []
    if analysis_method != SUPPORTED_ANALYSIS_METHOD:
        return {
            "profile": profile_id,
            "analysis_method": analysis_method,
            "scheduler_compatible": False,
            "verdict": "BLOCKED",
            "tasks": {},
            "interrupts": {},
            "cores": {},
            "flows": {},
            "problems": [
                f"{profile_id} analysis method {analysis_method!r} has no installed analyzer"
            ],
            "failures": [],
            "soft_risks": [],
            "fingerprint": _task_fingerprint(profile_id, units, channels),
        }
    scheduler = profile.get("scheduler")
    if not isinstance(scheduler, dict):
        scheduler = {}
        problems.append(f"{profile_id}.scheduler must be a mapping")
    expected_scheduler = {
        "model": "partitioned-fixed-priority",
        "priority_assignment": "rate-monotonic",
        "preemption": "fully-preemptive",
        "migration": "forbidden",
    }
    for field, expected in expected_scheduler.items():
        if scheduler.get(field) != expected:
            problems.append(f"{profile_id}.scheduler.{field} must equal {expected!r}")
    core_count = scheduler.get("core_count")
    if not _positive_int(core_count):
        problems.append(f"{profile_id}.scheduler.core_count must be positive")
        core_count = 0
    if not isinstance(scheduler.get("priority_higher_value_wins"), bool):
        problems.append(
            f"{profile_id}.scheduler.priority_higher_value_wins must be boolean"
        )
    if not _positive_int(scheduler.get("timer_resolution_ns")):
        problems.append(
            f"{profile_id}.scheduler.timer_resolution_ns must be positive"
        )
    if not isinstance(scheduler.get("resource_access_protocol"), str) or not scheduler.get(
        "resource_access_protocol"
    ):
        problems.append(
            f"{profile_id}.scheduler.resource_access_protocol is required"
        )
    scheduler_compatible = not problems

    channel_costs: dict[str, int] = {}
    profile_channels = {
        channel_id: item
        for channel_id, item in channels.items()
        if item.get("profile") == profile_id
    }
    for channel_id, channel in profile_channels.items():
        timing = channel.get("realtime_timing")
        if not isinstance(timing, dict):
            problems.append(f"{channel_id}.realtime_timing must be a mapping")
            continue
        for field in (
            "notification_latency_ns",
            "release_jitter_ns",
            "copy_cost_ns",
        ):
            if not _nonnegative_int(timing.get(field)):
                problems.append(
                    f"{channel_id}.realtime_timing.{field} must be nonnegative"
                )
        accounting = timing.get("cpu_cost_accounting")
        if not isinstance(accounting, list):
            problems.append(
                f"{channel_id}.realtime_timing.cpu_cost_accounting must be a list"
            )
            accounting = []
        total = 0
        seen_units: set[str] = set()
        for index, raw in enumerate(accounting):
            location = f"{channel_id}.realtime_timing.cpu_cost_accounting[{index}]"
            if not isinstance(raw, dict):
                problems.append(f"{location} must be a mapping")
                continue
            unit_id = raw.get("unit")
            cost = raw.get("cost_ns")
            if unit_id not in {channel.get("from_unit"), channel.get("to_unit")}:
                problems.append(f"{location}.unit must be the source or target unit")
            elif unit_id in seen_units:
                problems.append(f"{location}.unit duplicates {unit_id!r}")
            else:
                seen_units.add(str(unit_id))
            if not _nonnegative_int(cost):
                problems.append(f"{location}.cost_ns must be nonnegative")
                continue
            total += cost
            channel_costs[str(unit_id)] = channel_costs.get(str(unit_id), 0) + cost
        if _nonnegative_int(timing.get("copy_cost_ns")) and total != timing.get(
            "copy_cost_ns"
        ):
            problems.append(
                f"{channel_id} CPU cost accounting {total}ns does not equal "
                f"copy_cost_ns {timing.get('copy_cost_ns')}ns"
            )

    profile_units = {
        unit_id: item
        for unit_id, item in units.items()
        if item.get("profile") == profile_id and item.get("kind") == "dedicated-task"
    }
    interrupt_rows: dict[str, dict[str, Any]] = {}
    for unit_id, unit in units.items():
        if unit.get("profile") != profile_id or unit.get("kind") != "interrupt":
            continue
        isr = unit.get("interrupt_interference")
        if not isinstance(isr, dict):
            problems.append(f"{unit_id}.interrupt_interference must be a mapping")
            continue
        core = isr.get("core")
        wcet = isr.get("wcet_ns")
        period = isr.get("minimum_interarrival_ns")
        jitter = isr.get("release_jitter_ns")
        if not isinstance(core, int) or isinstance(core, bool) or not 0 <= core < core_count:
            problems.append(
                f"{unit_id}.interrupt_interference.core must select an available core"
            )
        if not _positive_int(wcet):
            problems.append(f"{unit_id}.interrupt_interference.wcet_ns must be positive")
        if not _positive_int(period):
            problems.append(
                f"{unit_id}.interrupt_interference.minimum_interarrival_ns must be positive"
            )
        if not _nonnegative_int(jitter):
            problems.append(
                f"{unit_id}.interrupt_interference.release_jitter_ns must be nonnegative"
            )
        interrupt_rows[unit_id] = {
            "id": unit_id,
            "core": core,
            "execution_ns": wcet if _positive_int(wcet) else 0,
            "period_ns": period if _positive_int(period) else 0,
            "jitter_ns": jitter if _nonnegative_int(jitter) else 0,
        }
    mapped_task_ids = {
        str(unit_id)
        for mapping in mappings.values()
        if mapping.get("profile") == profile_id
        for unit_id in mapping.get("units", [])
        if unit_id in profile_units
    }
    if set(profile_units) != mapped_task_ids:
        problems.append(
            f"{profile_id} every dedicated real-time task must appear in an execution mapping"
        )

    task_rows: dict[str, dict[str, Any]] = {}
    used_mappings: set[str] = set()
    for unit_id, unit in profile_units.items():
        task = unit.get("realtime_task")
        if not isinstance(task, dict):
            problems.append(f"{unit_id}.realtime_task must be a mapping")
            continue
        core = task.get("core")
        if not isinstance(core, int) or isinstance(core, bool) or not 0 <= core < core_count:
            problems.append(f"{unit_id}.realtime_task.core must select an available core")
        period = _effective_period(task)
        if period is None:
            problems.append(f"{unit_id}.realtime_task.activation is not analyzable")
            period = 0
        activation = task.get("activation", {})
        if isinstance(activation, dict) and activation.get("kind") not in {
            "periodic",
            "sporadic",
            "server",
        }:
            problems.append(
                f"{unit_id}.realtime_task.activation.kind must be periodic, sporadic, or server"
            )
        deadline = task.get("relative_deadline_ns")
        if not _positive_int(deadline):
            problems.append(
                f"{unit_id}.realtime_task.relative_deadline_ns must be positive"
            )
            deadline = 0
        for field in ("release_jitter_ns", "blocking_ns"):
            if not _nonnegative_int(task.get(field)):
                problems.append(f"{unit_id}.realtime_task.{field} must be nonnegative")
        priority = unit.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            problems.append(
                f"{unit_id}.priority must be an integer for analyzed profiles"
            )
        for component in task.get("demand_components", []):
            if not isinstance(component, dict):
                continue
            mapping_id = component.get("mapping")
            if mapping_id not in mappings or mappings.get(mapping_id, {}).get(
                "profile"
            ) != profile_id:
                problems.append(
                    f"{unit_id} demand component references unknown profile mapping "
                    f"{mapping_id!r}"
                )
            elif mapping_id in used_mappings:
                problems.append(
                    f"{mapping_id!r} is accounted by more than one real-time task"
                )
            else:
                used_mappings.add(str(mapping_id))
        execution = _task_cost(unit, profile, channel_costs, problems)
        task_rows[unit_id] = {
            "id": unit_id,
            "core": core,
            "period_ns": period,
            "deadline_ns": deadline,
            "jitter_ns": task.get("release_jitter_ns", 0),
            "blocking_ns": task.get("blocking_ns", 0),
            "execution_ns": execution,
            "priority": priority,
            "timing_class": _task_timing_class(task, mappings, workloads),
        }

    timer_resolution = scheduler.get("timer_resolution_ns")
    if _positive_int(timer_resolution):
        for row in task_rows.values():
            if row["period_ns"] and row["period_ns"] % timer_resolution != 0:
                problems.append(
                    f"{row['id']} effective period must be a multiple of timer resolution"
                )
        for row in interrupt_rows.values():
            if row["period_ns"] and row["period_ns"] % timer_resolution != 0:
                problems.append(
                    f"{row['id']} minimum inter-arrival must be a multiple of timer resolution"
                )

    profile_mapping_ids = {
        mapping_id
        for mapping_id, mapping in mappings.items()
        if mapping.get("profile") == profile_id
        and any(unit_id in profile_units for unit_id in mapping.get("units", []))
    }
    if used_mappings != profile_mapping_ids:
        missing = sorted(profile_mapping_ids - used_mappings)
        if missing:
            problems.append(
                f"{profile_id} mappings lack exactly-once WCET accounting: {missing}"
            )

    for channel_id, channel in profile_channels.items():
        timing = channel.get("realtime_timing")
        if not isinstance(timing, dict):
            continue
        source = task_rows.get(str(channel.get("from_unit")))
        target = task_rows.get(str(channel.get("to_unit")))
        if source is None or target is None:
            problems.append(
                f"{channel_id} analyzed channels must connect dedicated tasks"
            )
            continue
        actual_cross_core = source["core"] != target["core"]
        if timing.get("cross_core") is not actual_cross_core:
            problems.append(
                f"{channel_id}.realtime_timing.cross_core does not match task allocation"
            )

    higher_value = scheduler.get("priority_higher_value_wins") is True
    preemption_cost = profile.get("overheads", {}).get("preemption_ns", 0)
    if not _nonnegative_int(preemption_cost):
        problems.append(f"{profile_id}.overheads.preemption_ns must be nonnegative")
        preemption_cost = 0

    ordered_tasks_by_core: dict[int, list[dict[str, Any]]] = {}
    for core in range(core_count):
        ordered = [row for row in task_rows.values() if row["core"] == core]
        ordered.sort(
            key=lambda row: (row["period_ns"], row["deadline_ns"], row["id"])
        )
        ordered_tasks_by_core[core] = ordered
        priorities = [row["priority"] for row in ordered]
        if all(
            isinstance(priority, int) and not isinstance(priority, bool)
            for priority in priorities
        ):
            if len(priorities) != len(set(priorities)):
                problems.append(f"{profile_id}.core[{core}] priorities must be unique")
            expected_priority_order = sorted(priorities, reverse=higher_value)
            if priorities != expected_priority_order:
                problems.append(
                    f"{profile_id}.core[{core}] OS priorities do not match RM ordering"
                )

    # Configuration defects are authoritative BLOCKED results. Do not feed
    # sentinel zero periods, deadlines, or costs into fixed-point arithmetic.
    if problems:
        return {
            "profile": profile_id,
            "analysis_method": analysis_method,
            "verdict": "BLOCKED",
            "tasks": {
                task_id: {
                    **row,
                    "response_ns": None,
                    "rta_verdict": "BLOCKED",
                }
                for task_id, row in task_rows.items()
            },
            "interrupts": interrupt_rows,
            "cores": {},
            "flows": {},
            "problems": problems,
            "failures": failures,
            "soft_risks": soft_risks,
            "fingerprint": _task_fingerprint(profile_id, units, channels),
        }

    task_results: dict[str, dict[str, Any]] = {}
    core_results: dict[str, dict[str, Any]] = {}
    for core in range(core_count):
        core_tasks = ordered_tasks_by_core[core]
        core_interrupts = [
            row for row in interrupt_rows.values() if row["core"] == core
        ]
        utilization = Fraction(0, 1)
        for row in core_interrupts:
            if row["period_ns"]:
                utilization += Fraction(row["execution_ns"], row["period_ns"])
        for row in core_tasks:
            if row["period_ns"]:
                utilization += Fraction(row["execution_ns"], row["period_ns"])
        n = len(core_tasks)
        sufficient_bound = n * (2 ** (1 / n) - 1) if n else 0.0
        core_results[str(core)] = {
            "rm_order": [row["id"] for row in core_tasks],
            "interrupts": [row["id"] for row in core_interrupts],
            "utilization": float(utilization),
            "liu_layland_bound": sufficient_bound,
            "sufficient_bound_pass": (
                not core_interrupts and float(utilization) <= sufficient_bound
            ) if n else not core_interrupts,
        }
        for index, row in enumerate(core_tasks):
            higher = core_tasks[:index]
            same_or_higher = higher + [row]
            busy = row["blocking_ns"] + sum(
                item["execution_ns"] for item in same_or_higher
            )
            busy += sum(item["execution_ns"] for item in core_interrupts)
            busy_converged = False
            for _ in range(max_iterations):
                next_busy = row["blocking_ns"] + sum(
                    ceil((busy + item["jitter_ns"]) / item["period_ns"])
                    * (
                        item["execution_ns"]
                        + (preemption_cost if item is not row else 0)
                    )
                    for item in same_or_higher
                    if item["period_ns"]
                )
                next_busy += sum(
                    ceil((busy + isr["jitter_ns"]) / isr["period_ns"])
                    * isr["execution_ns"]
                    for isr in core_interrupts
                    if isr["period_ns"]
                )
                if next_busy == busy:
                    busy_converged = True
                    break
                busy = next_busy
            if not busy_converged:
                problems.append(f"{row['id']} level-i busy period did not converge")
                task_results[row["id"]] = {
                    **row,
                    "response_ns": None,
                    "rta_verdict": "BLOCKED",
                }
                continue

            jobs = max(1, ceil(busy / row["period_ns"]))
            worst_response = 0
            response_converged = True
            for job_index in range(jobs):
                window = (
                    row["blocking_ns"]
                    + (job_index + 1) * row["execution_ns"]
                )
                converged = False
                for _ in range(max_iterations):
                    interference = sum(
                        ceil((window + hp["jitter_ns"]) / hp["period_ns"])
                        * (hp["execution_ns"] + preemption_cost)
                        for hp in higher
                        if hp["period_ns"]
                    )
                    interference += sum(
                        ceil((window + isr["jitter_ns"]) / isr["period_ns"])
                        * isr["execution_ns"]
                        for isr in core_interrupts
                        if isr["period_ns"]
                    )
                    next_window = (
                        row["blocking_ns"]
                        + (job_index + 1) * row["execution_ns"]
                        + interference
                    )
                    if next_window == window:
                        converged = True
                        break
                    window = next_window
                if not converged:
                    response_converged = False
                    break
                worst_response = max(
                    worst_response,
                    window - job_index * row["period_ns"] + row["jitter_ns"],
                )
            if not response_converged:
                problems.append(f"{row['id']} arbitrary-deadline RTA did not converge")
                rta_verdict = "BLOCKED"
            elif worst_response > row["deadline_ns"]:
                miss = (
                    f"{row['id']} response {worst_response}ns exceeds deadline "
                    f"{row['deadline_ns']}ns"
                )
                if row["timing_class"] == "hard-real-time":
                    failures.append(miss)
                    rta_verdict = "FAIL"
                elif row["timing_class"] == "soft-real-time":
                    soft_risks.append(miss)
                    rta_verdict = "SOFT_RISK"
                else:
                    rta_verdict = "INFO"
            else:
                rta_verdict = "PASS"
            task_results[row["id"]] = {
                **row,
                "response_ns": worst_response,
                "rta_verdict": rta_verdict,
            }

    flow_results: dict[str, dict[str, Any]] = {}
    for raw in flow_chains or []:
        if not isinstance(raw, dict) or raw.get("profile") != profile_id:
            continue
        chain_id = str(raw.get("id"))
        ordered_units = raw.get("ordered_units")
        ordered_channels = raw.get("ordered_channels")
        deadline = raw.get("deadline_ns")
        if not isinstance(ordered_units, list) or not ordered_units:
            problems.append(f"{chain_id}.ordered_units must not be empty")
            continue
        if not isinstance(ordered_channels, list):
            problems.append(f"{chain_id}.ordered_channels must be a list")
            continue
        if len(ordered_channels) != max(0, len(ordered_units) - 1):
            problems.append(
                f"{chain_id} requires one channel between adjacent ordered units"
            )
            continue
        if not _positive_int(deadline):
            problems.append(f"{chain_id}.deadline_ns must be positive")
            continue
        bound = 0
        valid = True
        for unit_id in ordered_units:
            result = task_results.get(str(unit_id))
            if result is None:
                problems.append(f"{chain_id} references unknown task {unit_id!r}")
                valid = False
            elif not _nonnegative_int(result.get("response_ns")):
                problems.append(
                    f"{chain_id} cannot use task {unit_id!r} without a valid RTA bound"
                )
                valid = False
            else:
                bound += result["response_ns"]
        for index, channel_id in enumerate(ordered_channels):
            channel = profile_channels.get(str(channel_id))
            if channel is None:
                problems.append(f"{chain_id} references unknown channel {channel_id!r}")
                valid = False
                continue
            if channel.get("from_unit") != ordered_units[index] or channel.get(
                "to_unit"
            ) != ordered_units[index + 1]:
                problems.append(
                    f"{chain_id} channel {channel_id!r} does not connect adjacent tasks"
                )
                valid = False
            timing = channel.get("realtime_timing", {})
            if isinstance(timing, dict):
                bound += timing.get("notification_latency_ns", 0)
                bound += timing.get("release_jitter_ns", 0)
        if not valid:
            continue
        timing_class = _flow_timing_class(
            profile_id, raw.get("flow"), mappings, workloads
        )
        if bound <= deadline:
            rta_verdict = "PASS"
        else:
            miss = f"{chain_id} response {bound}ns exceeds deadline {deadline}ns"
            if timing_class == "hard-real-time":
                failures.append(miss)
                rta_verdict = "FAIL"
            elif timing_class == "soft-real-time":
                soft_risks.append(miss)
                rta_verdict = "SOFT_RISK"
            else:
                rta_verdict = "INFO"
        flow_results[chain_id] = {
            "flow": raw.get("flow"),
            "timing_class": timing_class,
            "response_ns": bound,
            "deadline_ns": deadline,
            "rta_verdict": rta_verdict,
        }

    verdict = "BLOCKED" if problems else ("FAIL" if failures else "PASS")
    return {
        "profile": profile_id,
        "analysis_method": analysis_method,
        "scheduler_compatible": scheduler_compatible,
        "verdict": verdict,
        "tasks": task_results,
        "interrupts": interrupt_rows,
        "cores": core_results,
        "flows": flow_results,
        "problems": problems,
        "failures": failures,
        "soft_risks": soft_risks,
        "fingerprint": _task_fingerprint(profile_id, units, channels),
    }
