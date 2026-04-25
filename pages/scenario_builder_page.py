"""Scenario builder page — author scenario JSONs from the UI."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from backtest.registry import (
    EXIT_SCHEMAS,
    EXITS,
    TRIGGER_SCHEMAS,
    TRIGGERS,
    UNIVERSE_FILTER_SCHEMAS,
    UNIVERSE_FILTERS,
)

# Force component registration so registries are populated.
import backtest.filters  # noqa: F401
import backtest.triggers  # noqa: F401
import backtest.exits  # noqa: F401

from view_helpers import CARD_STYLE

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path("backtest/scenarios")

INPUT_STYLE = {
    "padding": "5px 8px",
    "backgroundColor": "#1e293b",
    "color": "#e2e8f0",
    "border": "1px solid #334155",
    "borderRadius": "4px",
    "fontFamily": "monospace",
    "fontSize": "13px",
    "minWidth": "120px",
}

LABEL_STYLE = {"fontSize": "13px", "color": "#94a3b8", "minWidth": "200px"}

SECTION_STYLE = {**CARD_STYLE, "marginBottom": "12px"}


def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s.strip())
    return re.sub(r"_+", "_", s).strip("_")


def _coerce_scalar(field_type: str, raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if field_type in ("int", "nullable_int"):
        return int(float(raw))
    if field_type in ("float", "nullable_float"):
        return float(raw)
    if field_type == "bool":
        if isinstance(raw, list):
            return "yes" in raw
        return bool(raw)
    return raw


def _parse_sweep_csv(field_type: str, csv: str) -> List[Any]:
    if not csv:
        return []
    parts = [p.strip() for p in csv.split(",") if p.strip()]
    return [_coerce_scalar(field_type, p) for p in parts]


def _parse_int_pair(text: str) -> List[int]:
    nums = re.findall(r"-?\d+", text or "")
    if len(nums) < 2:
        raise ValueError("expected two integers")
    return [int(nums[0]), int(nums[1])]


def _render_param_field(section: str, schema: Dict[str, Any]) -> html.Div:
    name = schema["name"]
    field_type = schema["type"]
    label = schema.get("label", name)
    default = schema.get("default")
    sweepable = bool(schema.get("sweepable", False))

    base_id = {"section": section, "field": name}
    children: List[Any] = [html.Span(label, style=LABEL_STYLE)]

    if field_type == "bool":
        children.append(
            dcc.Checklist(
                id={**base_id, "role": "value"},
                options=[{"label": "", "value": "yes"}],
                value=["yes"] if default else [],
            )
        )
    elif field_type == "enum":
        children.append(
            dcc.Dropdown(
                id={**base_id, "role": "value"},
                options=[{"label": c, "value": c} for c in schema["choices"]],
                value=default,
                clearable=False,
                style={"width": "180px", "color": "#111"},
            )
        )
    elif field_type == "int_pair":
        children.append(
            dcc.Input(
                id={**base_id, "role": "value"},
                type="text",
                value=", ".join(str(x) for x in (default or [])),
                placeholder="lo, hi",
                style=INPUT_STYLE,
            )
        )
    else:  # int / float / nullable_int / nullable_float
        children.append(
            dcc.Input(
                id={**base_id, "role": "value"},
                type="number" if "nullable" not in field_type else "text",
                value=default if default is not None else "",
                style=INPUT_STYLE,
            )
        )

    if sweepable:
        children.append(
            dcc.Checklist(
                id={**base_id, "role": "sweep_toggle"},
                options=[{"label": "sweep", "value": "yes"}],
                value=[],
                style={"marginLeft": "8px"},
            )
        )
        children.append(
            dcc.Input(
                id={**base_id, "role": "sweep_values"},
                type="text",
                placeholder="comma-separated, e.g. 5, 10, 15",
                style={**INPUT_STYLE, "minWidth": "240px", "display": "none"},
            )
        )

    children.append(
        dcc.Store(
            id={**base_id, "role": "meta"},
            data={"type": field_type, "sweepable": sweepable},
        )
    )

    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "8px"},
        children=children,
    )


def _render_param_block(section: str, schemas: List[Dict[str, Any]]) -> html.Div:
    if not schemas:
        return html.Div(html.Em("(no parameters)", style={"color": "#888"}))
    return html.Div([_render_param_field(section, s) for s in schemas])


class ScenarioBuilderPage:
    """Build scenario JSON files via a guided form."""

    route = "/scenario-builder"
    title = "Scenario Builder"

    def __init__(self):
        pass

    def layout(self):
        filter_opts = [{"label": n, "value": n} for n in sorted(UNIVERSE_FILTERS)]
        trigger_opts = [{"label": n, "value": n} for n in sorted(TRIGGERS)]
        exit_opts = [{"label": n, "value": n} for n in sorted(EXITS)]

        first_filter = filter_opts[0]["value"] if filter_opts else None
        first_trigger = trigger_opts[0]["value"] if trigger_opts else None
        first_exit = exit_opts[0]["value"] if exit_opts else None

        return html.Div([
            html.H2("Scenario Builder", style={"marginBottom": "10px"}),
            html.P(
                f"Save target: {SCENARIOS_DIR}/<name>.json. Sweep checkbox replaces a single value with a comma-separated list (Cartesian product across all swept axes).",
                style={"color": "#888", "fontSize": "13px"},
            ),

            html.Div(style=SECTION_STYLE, children=[
                html.H4("Identity"),
                html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=[
                    html.Div([
                        html.Label("Name", style=LABEL_STYLE),
                        dcc.Input(id="sb-name", type="text", placeholder="my_strategy", style=INPUT_STYLE),
                    ]),
                    html.Div([
                        html.Label("Description", style=LABEL_STYLE),
                        dcc.Input(id="sb-description", type="text",
                                  placeholder="optional", style={**INPUT_STYLE, "minWidth": "320px"}),
                    ]),
                    html.Div([
                        html.Label("Side target", style=LABEL_STYLE),
                        dcc.Dropdown(id="sb-side-target",
                                     options=[{"label": "favorite", "value": "favorite"},
                                              {"label": "underdog", "value": "underdog"}],
                                     value="favorite", clearable=False,
                                     style={"width": "160px", "color": "#111"}),
                    ]),
                    html.Div([
                        html.Label("Fee model", style=LABEL_STYLE),
                        dcc.Dropdown(id="sb-fee-model",
                                     options=[{"label": "default", "value": "default"},
                                              {"label": "taker", "value": "taker"}],
                                     value="default", clearable=False,
                                     style={"width": "160px", "color": "#111"}),
                    ]),
                ]),
            ]),

            html.Div(style=SECTION_STYLE, children=[
                html.H4("Universe Filter"),
                dcc.Dropdown(id="sb-filter-name", options=filter_opts, value=first_filter,
                             clearable=False, style={"width": "320px", "color": "#111", "marginBottom": "10px"}),
                html.Div(id="sb-filter-params"),
            ]),

            html.Div(style=SECTION_STYLE, children=[
                html.H4("Trigger"),
                dcc.Dropdown(id="sb-trigger-name", options=trigger_opts, value=first_trigger,
                             clearable=False, style={"width": "320px", "color": "#111", "marginBottom": "10px"}),
                html.Div(id="sb-trigger-params"),
            ]),

            html.Div(style=SECTION_STYLE, children=[
                html.H4("Exit"),
                dcc.Dropdown(id="sb-exit-name", options=exit_opts, value=first_exit,
                             clearable=False, style={"width": "320px", "color": "#111", "marginBottom": "10px"}),
                html.Div(id="sb-exit-params"),
            ]),

            html.Div(style=SECTION_STYLE, children=[
                html.H4("Lock policy"),
                html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=[
                    html.Div([
                        html.Label("Mode", style=LABEL_STYLE),
                        dcc.Dropdown(id="sb-lock-mode",
                                     options=[{"label": "sequential", "value": "sequential"},
                                              {"label": "scale_in", "value": "scale_in"}],
                                     value="sequential", clearable=False,
                                     style={"width": "160px", "color": "#111"}),
                    ]),
                    html.Div([
                        html.Label("max_entries", style=LABEL_STYLE),
                        dcc.Input(id="sb-lock-max-entries", type="number", value=1,
                                  min=1, step=1, style=INPUT_STYLE),
                    ]),
                    html.Div([
                        html.Label("cool_down_seconds", style=LABEL_STYLE),
                        dcc.Input(id="sb-lock-cooldown", type="number", value=0,
                                  min=0, step=1, style=INPUT_STYLE),
                    ]),
                    html.Div([
                        html.Label("re-arm after stop_loss", style=LABEL_STYLE),
                        dcc.Checklist(id="sb-lock-rearm",
                                      options=[{"label": "", "value": "yes"}], value=[]),
                    ]),
                ]),
            ]),

            html.Div(style={"display": "flex", "gap": "10px", "marginBottom": "20px"}, children=[
                html.Button("Preview JSON", id="sb-preview-btn",
                            style={"padding": "8px 14px", "backgroundColor": "#475569",
                                   "color": "#fff", "border": "none", "borderRadius": "6px",
                                   "cursor": "pointer"}),
                html.Button("Save scenario", id="sb-save-btn",
                            style={"padding": "8px 14px", "backgroundColor": "#22c55e",
                                   "color": "#111", "border": "none", "borderRadius": "6px",
                                   "fontWeight": "bold", "cursor": "pointer"}),
                html.Span(id="sb-status", style={"alignSelf": "center", "color": "#fbbf24"}),
            ]),

            html.Div(style=SECTION_STYLE, children=[
                html.H4("Preview"),
                html.Pre(id="sb-preview", style={"backgroundColor": "#0f172a",
                                                  "padding": "12px", "borderRadius": "6px",
                                                  "color": "#e2e8f0", "fontSize": "12px",
                                                  "whiteSpace": "pre-wrap"}),
            ]),
        ])

    def register_callbacks(self, app):
        @app.callback(
            Output("sb-filter-params", "children"),
            Input("sb-filter-name", "value"),
        )
        def render_filter_params(name):
            schema = UNIVERSE_FILTER_SCHEMAS.get(name, [])
            return _render_param_block("universe_filter", schema)

        @app.callback(
            Output("sb-trigger-params", "children"),
            Input("sb-trigger-name", "value"),
        )
        def render_trigger_params(name):
            schema = TRIGGER_SCHEMAS.get(name, [])
            return _render_param_block("trigger", schema)

        @app.callback(
            Output("sb-exit-params", "children"),
            Input("sb-exit-name", "value"),
        )
        def render_exit_params(name):
            schema = EXIT_SCHEMAS.get(name, [])
            return _render_param_block("exit", schema)

        @app.callback(
            Output({"section": ALL, "field": ALL, "role": "sweep_values"}, "style"),
            Input({"section": ALL, "field": ALL, "role": "sweep_toggle"}, "value"),
            prevent_initial_call=False,
        )
        def toggle_sweep_visibility(toggles):
            styles_out = []
            for t in toggles:
                style = {**INPUT_STYLE, "minWidth": "240px"}
                style["display"] = "block" if (t and "yes" in t) else "none"
                styles_out.append(style)
            return styles_out

        @app.callback(
            Output("sb-preview", "children"),
            Output("sb-status", "children"),
            Output("sb-status", "style"),
            Input("sb-preview-btn", "n_clicks"),
            Input("sb-save-btn", "n_clicks"),
            State("sb-name", "value"),
            State("sb-description", "value"),
            State("sb-side-target", "value"),
            State("sb-fee-model", "value"),
            State("sb-filter-name", "value"),
            State("sb-trigger-name", "value"),
            State("sb-exit-name", "value"),
            State("sb-lock-mode", "value"),
            State("sb-lock-max-entries", "value"),
            State("sb-lock-cooldown", "value"),
            State("sb-lock-rearm", "value"),
            State({"section": ALL, "field": ALL, "role": "value"}, "value"),
            State({"section": ALL, "field": ALL, "role": "value"}, "id"),
            State({"section": ALL, "field": ALL, "role": "sweep_toggle"}, "value"),
            State({"section": ALL, "field": ALL, "role": "sweep_toggle"}, "id"),
            State({"section": ALL, "field": ALL, "role": "sweep_values"}, "value"),
            State({"section": ALL, "field": ALL, "role": "sweep_values"}, "id"),
            State({"section": ALL, "field": ALL, "role": "meta"}, "data"),
            State({"section": ALL, "field": ALL, "role": "meta"}, "id"),
            prevent_initial_call=True,
        )
        def build_or_save(
            preview_clicks, save_clicks,
            name, description, side_target, fee_model,
            filter_name, trigger_name, exit_name,
            lock_mode, lock_max_entries, lock_cooldown, lock_rearm,
            value_values, value_ids,
            sweep_toggles, sweep_toggle_ids,
            sweep_values, sweep_value_ids,
            meta_data, meta_ids,
        ):
            triggered = ctx.triggered_id
            try:
                scenario_dict = self._compose_scenario(
                    name=name, description=description, side_target=side_target,
                    fee_model=fee_model, filter_name=filter_name,
                    trigger_name=trigger_name, exit_name=exit_name,
                    lock_mode=lock_mode, lock_max_entries=lock_max_entries,
                    lock_cooldown=lock_cooldown, lock_rearm=lock_rearm,
                    value_values=value_values, value_ids=value_ids,
                    sweep_toggles=sweep_toggles, sweep_toggle_ids=sweep_toggle_ids,
                    sweep_values=sweep_values, sweep_value_ids=sweep_value_ids,
                    meta_data=meta_data, meta_ids=meta_ids,
                )
            except ValueError as exc:
                return no_update, f"Error: {exc}", {"alignSelf": "center", "color": "#f87171"}

            preview = json.dumps(scenario_dict, indent=2)

            if triggered == "sb-save-btn":
                slug = _slug(scenario_dict["name"])
                if not slug:
                    return preview, "Error: invalid name", {"alignSelf": "center", "color": "#f87171"}
                SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
                target = SCENARIOS_DIR / f"{slug}.json"
                if target.exists():
                    return preview, f"Error: {target.name} already exists", {"alignSelf": "center", "color": "#f87171"}
                target.write_text(preview + "\n")
                return preview, f"Saved → {target}", {"alignSelf": "center", "color": "#34d399"}

            return preview, "", {"alignSelf": "center"}

    @staticmethod
    def _compose_scenario(
        *, name, description, side_target, fee_model,
        filter_name, trigger_name, exit_name,
        lock_mode, lock_max_entries, lock_cooldown, lock_rearm,
        value_values, value_ids,
        sweep_toggles, sweep_toggle_ids,
        sweep_values, sweep_value_ids,
        meta_data, meta_ids,
    ) -> Dict[str, Any]:
        if not name:
            raise ValueError("scenario name is required")
        if not filter_name:
            raise ValueError("universe filter is required")
        if not trigger_name:
            raise ValueError("trigger is required")
        if not exit_name:
            raise ValueError("exit is required")

        # index pattern-match outputs by (section, field)
        meta_by_key = {(m["section"], m["field"]): d for m, d in zip(meta_ids, meta_data)}
        value_by_key = {(i["section"], i["field"]): v for i, v in zip(value_ids, value_values)}
        sweep_toggle_by_key = {(i["section"], i["field"]): v for i, v in zip(sweep_toggle_ids, sweep_toggles)}
        sweep_values_by_key = {(i["section"], i["field"]): v for i, v in zip(sweep_value_ids, sweep_values)}

        sections: Dict[str, Dict[str, Any]] = {"universe_filter": {}, "trigger": {}, "exit": {}}
        for (section, field), meta in meta_by_key.items():
            field_type = meta["type"]
            sweep_on = (
                bool(meta.get("sweepable"))
                and (section, field) in sweep_toggle_by_key
                and "yes" in (sweep_toggle_by_key.get((section, field)) or [])
            )
            if sweep_on:
                csv = sweep_values_by_key.get((section, field)) or ""
                values = _parse_sweep_csv(field_type, csv)
                if not values:
                    raise ValueError(f"sweep for '{field}' has no values")
                sections[section][field] = {"sweep": values}
                continue

            raw = value_by_key.get((section, field))
            if field_type == "int_pair":
                if raw in (None, "", []):
                    if meta.get("nullable"):
                        continue
                    raise ValueError(f"'{field}' requires lo, hi")
                sections[section][field] = _parse_int_pair(str(raw))
            elif field_type == "bool":
                sections[section][field] = _coerce_scalar(field_type, raw)
            elif field_type in ("nullable_int", "nullable_float"):
                if raw in (None, ""):
                    sections[section][field] = None
                else:
                    sections[section][field] = _coerce_scalar(field_type, raw)
            else:
                if raw is None or raw == "":
                    raise ValueError(f"'{field}' is required")
                sections[section][field] = _coerce_scalar(field_type, raw)

        scenario: Dict[str, Any] = {
            "name": _slug(name),
            "universe_filter": {"name": filter_name, "params": sections["universe_filter"]},
            "side_target": side_target or "favorite",
            "trigger": {"name": trigger_name, "params": sections["trigger"]},
            "exit": {"name": exit_name, "params": sections["exit"]},
            "lock": {
                "mode": lock_mode or "sequential",
                "max_entries": int(lock_max_entries or 1),
                "cool_down_seconds": float(lock_cooldown or 0),
                "allow_re_arm_after_stop_loss": bool(lock_rearm and "yes" in lock_rearm),
            },
            "fee_model": fee_model or "default",
        }
        if description:
            scenario["description"] = description
        return scenario
