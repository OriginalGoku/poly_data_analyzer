"""Scenario JSON loader with sweep expansion."""
from __future__ import annotations

import copy
import glob
import itertools
import json
import os
from typing import Any, Dict, Iterable, List, Tuple

from backtest.contracts import ComponentSpec, LockSpec, Scenario

REQUIRED_KEYS = (
    "name",
    "universe_filter",
    "side_target",
    "trigger",
    "exit",
    "lock",
    "fee_model",
)


def _is_sweep(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and len(node) == 1
        and "sweep" in node
        and isinstance(node["sweep"], list)
    )


def _find_sweeps(node: Any, path: Tuple[str, ...] = ()) -> Iterable[Tuple[Tuple[str, ...], List[Any]]]:
    """Yield (dot-path, values) for every {"sweep": [...]} marker in node."""
    if _is_sweep(node):
        yield path, list(node["sweep"])
        return
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _find_sweeps(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _find_sweeps(v, path + (str(i),))


def _set_path(root: Any, path: Tuple[str, ...], value: Any) -> None:
    cur = root
    for key in path[:-1]:
        if isinstance(cur, list):
            cur = cur[int(key)]
        else:
            cur = cur[key]
    last = path[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _format_value(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _validate_no_residual_sweeps(node: Any, path: Tuple[str, ...] = ()) -> None:
    if _is_sweep(node):
        raise ValueError(f"unexpected sweep marker at {'.'.join(path) or '<root>'}")
    if isinstance(node, dict):
        for k, v in node.items():
            _validate_no_residual_sweeps(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _validate_no_residual_sweeps(v, path + (str(i),))


def _component(spec: Dict[str, Any]) -> ComponentSpec:
    return ComponentSpec(name=spec["name"], params=dict(spec.get("params", {})))


def _build_scenario(raw: Dict[str, Any], sweep_axes: Dict[str, Any]) -> Scenario:
    for key in REQUIRED_KEYS:
        if key not in raw:
            raise ValueError(f"scenario {raw.get('name', '<unknown>')} missing required key: {key}")
    lock_raw = raw["lock"]
    lock = LockSpec(
        mode=lock_raw["mode"],
        max_entries=int(lock_raw.get("max_entries", 1)),
        cool_down_seconds=float(lock_raw.get("cool_down_seconds", 0.0)),
        allow_re_arm_after_stop_loss=bool(lock_raw.get("allow_re_arm_after_stop_loss", False)),
    )
    return Scenario(
        name=raw["name"],
        universe_filter=_component(raw["universe_filter"]),
        side_target=raw["side_target"],
        trigger=_component(raw["trigger"]),
        exit=_component(raw["exit"]),
        lock=lock,
        fee_model=raw["fee_model"],
        sweep_axes=sweep_axes,
    )


def _expand(raw: Dict[str, Any]) -> List[Scenario]:
    sweeps = list(_find_sweeps(raw))
    if not sweeps:
        _validate_no_residual_sweeps(raw)
        return [_build_scenario(raw, sweep_axes={})]
    paths = [p for p, _ in sweeps]
    value_lists = [vals for _, vals in sweeps]
    base_name = raw["name"]
    out: List[Scenario] = []
    for combo in itertools.product(*value_lists):
        clone = copy.deepcopy(raw)
        axes: Dict[str, Any] = {}
        suffix_parts: List[str] = []
        for path, value in zip(paths, combo):
            _set_path(clone, path, value)
            dotted = ".".join(path)
            axes[dotted] = value
            suffix_parts.append(f"{dotted}={_format_value(value)}")
        clone["name"] = f"{base_name}__" + "__".join(suffix_parts)
        _validate_no_residual_sweeps(clone)
        out.append(_build_scenario(clone, sweep_axes=axes))
    return out


def load_scenarios(scenarios_dir: str = "backtest/scenarios") -> Dict[str, Scenario]:
    """Load and sweep-expand every *.json file in `scenarios_dir`.

    Returns a dict keyed by scenario name. Raises ValueError on duplicate names
    or schema violations.
    """
    out: Dict[str, Scenario] = {}
    if not os.path.isdir(scenarios_dir):
        return out
    for path in sorted(glob.glob(os.path.join(scenarios_dir, "*.json"))):
        with open(path, "r") as f:
            raw = json.load(f)
        for scenario in _expand(raw):
            if scenario.name in out:
                raise ValueError(f"duplicate scenario name: {scenario.name}")
            out[scenario.name] = scenario
    return out
