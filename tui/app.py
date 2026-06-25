"""QAura TUI — Main Textual Application."""

import sys
import os
import threading
import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, RichLog
from textual.containers import Horizontal
from textual.message import Message
from textual.worker import Worker, WorkerState

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.screens import RunConfigScreen, PlanApprovalScreen


class PipelineLog(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class PipelinePhaseChange(Message):
    def __init__(self, phase: str) -> None:
        self.phase = phase
        super().__init__()


class PipelinePlanReady(Message):
    def __init__(self, plan_data: dict) -> None:
        self.plan_data = plan_data
        super().__init__()


class PipelineComplete(Message):
    def __init__(self, final_state: dict | None) -> None:
        self.final_state = final_state
        super().__init__()


class QAuraApp(App):
    """QAura Testing Pipeline Dashboard."""

    CSS_PATH = "styles.tcss"
    TITLE = "QAura — Autonomous Testing Dashboard"
    BINDINGS = [
        ("r", "new_run", "New Run"),
        ("q", "quit", "Quit"),
        ("question_mark", "help_screen", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._approval_event = threading.Event()
        self._approval_result: dict | None = None
        self._pipeline_running = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Phase: Idle", id="phase-indicator")
        with Horizontal():
            yield RichLog(highlight=True, markup=True, id="activity-log")
            yield Static(
                "[b]Status[/b]\n\nNo run in progress.\n\nPress [b]r[/b] to start.",
                id="status-panel",
            )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#activity-log", RichLog)
        log.border_title = "Activity Log"
        status = self.query_one("#status-panel", Static)
        status.border_title = "Status"
        log.write("[bold green]QAura TUI ready.[/bold green]")
        log.write("Press [bold]r[/bold] to configure and start a pipeline run.")

    def action_new_run(self) -> None:
        if self._pipeline_running:
            self._log("A pipeline is already running.")
            return
        self.push_screen(RunConfigScreen(), callback=self._on_run_config)

    def action_help_screen(self) -> None:
        self._log("[bold]Keybindings:[/bold]")
        self._log("  r — Start a new pipeline run")
        self._log("  q — Quit the application")
        self._log("  ? — Show this help")

    def _on_run_config(self, result: dict | None) -> None:
        if result is None:
            self._log("Run cancelled.")
            return
        self._log(f"Starting pipeline with: {result['requirements_path']}")
        self._pipeline_running = True
        self._update_phase("Initializing")
        self.run_worker(
            self._run_pipeline(result),
            name="pipeline",
            group="pipeline",
            exclusive=True,
            thread=True,
        )

    def _run_pipeline(self, config: dict) -> None:
        """Background worker — runs the LangGraph pipeline."""
        from core.graph import graph, get_initial_state
        from langgraph.types import Command
        from tui.callbacks import TUICallbackHandler

        requirements_path = config["requirements_path"]
        thread_id = "qaura_tui_run"
        graph_config = {"configurable": {"thread_id": thread_id}}

        handler = TUICallbackHandler(self.post_message)
        initial_state = get_initial_state(requirements_path)
        initial_state["callbacks"] = [handler]
        self.post_message(PipelinePhaseChange("Phase 1: Planning"))
        self.post_message(PipelineLog("Running Test Architect agent..."))

        last_state = None
        for output in graph.stream(initial_state, config=graph_config, stream_mode="values"):
            last_state = output
            messages = output.get("messages", [])
            if messages:
                for msg in messages[-1:]:
                    self.post_message(PipelineLog(f"  → {msg}"))

        test_plan = last_state.get("test_plan") if last_state else None
        if test_plan:
            self.post_message(PipelinePhaseChange("HITL: Awaiting Approval"))
            self.post_message(PipelinePlanReady(test_plan.model_dump()))
        else:
            self.post_message(PipelineLog("[red]No test plan generated. Pipeline stopping.[/red]"))
            self.post_message(PipelineComplete(last_state))
            return

        self._approval_event.clear()
        self._approval_event.wait()
        approved = self._approval_result.get("approved", False) if self._approval_result else False

        if approved:
            self.post_message(PipelinePhaseChange("Phase 2: Test Generation"))
            self.post_message(PipelineLog("Plan approved. Generating tests..."))
        else:
            self.post_message(PipelineLog("[yellow]Plan rejected. Stopping pipeline.[/yellow]"))

        for output in graph.stream(
            Command(resume={"approved": approved}),
            config=graph_config,
            stream_mode="values",
        ):
            last_state = output
            messages = output.get("messages", [])
            if messages:
                for msg in messages[-1:]:
                    self.post_message(PipelineLog(f"  → {msg}"))

            if output.get("unit_tests"):
                self.post_message(PipelinePhaseChange("Phase 3: Execution"))

        self.post_message(PipelineComplete(last_state))

    def on_pipeline_log(self, message: PipelineLog) -> None:
        self._log(message.text)

    def on_pipeline_phase_change(self, message: PipelinePhaseChange) -> None:
        self._update_phase(message.phase)

    def on_pipeline_plan_ready(self, message: PipelinePlanReady) -> None:
        plan_md = self._format_plan_as_markdown(message.plan_data)
        self.push_screen(PlanApprovalScreen(plan_md), callback=self._on_plan_decision)

    def on_pipeline_complete(self, message: PipelineComplete) -> None:
        self._pipeline_running = False
        self._update_phase("Complete")
        state = message.final_state
        if state and state.get("execution_summary"):
            summary = state["execution_summary"]
            if hasattr(summary, "model_dump"):
                summary = summary.model_dump()
            self._update_status(
                f"[b]Execution Results[/b]\n\n"
                f"Total: {summary.get('total_tests', 0)}\n"
                f"Passed: {summary.get('passed', 0)}\n"
                f"Failed: {summary.get('failed', 0)}\n"
                f"Blocked: {summary.get('blocked', 0)}\n\n"
                f"Critical Path: {'✓' if summary.get('critical_path_success') else '✗'}"
            )
            self._log("[bold green]Pipeline complete.[/bold green]")
        elif state and state.get("plan_approved") is False:
            self._update_status("[b]Run Ended[/b]\n\nPlan was rejected.")
            self._log("Pipeline ended — plan was not approved.")
        else:
            self._update_status("[b]Run Ended[/b]\n\nPipeline finished.")
            self._log("Pipeline complete.")

    def _on_plan_decision(self, result: dict) -> None:
        self._approval_result = result
        self._approval_event.set()

    def _log(self, text: str) -> None:
        try:
            log = self.query_one("#activity-log", RichLog)
            log.write(text)
        except Exception:
            pass

    def _update_phase(self, phase: str) -> None:
        try:
            indicator = self.query_one("#phase-indicator", Static)
            indicator.update(f"Phase: {phase}")
        except Exception:
            pass

    def _update_status(self, text: str) -> None:
        try:
            panel = self.query_one("#status-panel", Static)
            panel.update(text)
        except Exception:
            pass

    def _format_plan_as_markdown(self, plan: dict) -> str:
        lines = [
            f"# Test Plan\n",
            f"**Summary:** {plan.get('project_summary', 'N/A')}\n",
            f"## Components ({len(plan.get('components', []))})\n",
        ]
        for comp in plan.get("components", []):
            risk = comp.get("risk_level", "?")
            emoji = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(risk, "⚪")
            lines.append(
                f"- {emoji} **{comp['name']}** ({comp.get('file_path', '')})"
                f" — {comp.get('testing_type', '')} | Risk: {risk}"
            )
        lines.append(f"\n## Scopes\n")
        lines.append(f"- **Unit:** {', '.join(plan.get('unit_scope', []))}")
        lines.append(f"- **Integration:** {', '.join(plan.get('integration_scope', []))}")
        lines.append(f"- **E2E:** {', '.join(plan.get('e2e_scope', []))}")
        lines.append(f"\n## Risk Areas\n")
        for risk in plan.get("risk_areas", []):
            lines.append(f"- {risk}")
        return "\n".join(lines)


def main():
    app = QAuraApp()
    app.run()


if __name__ == "__main__":
    main()
