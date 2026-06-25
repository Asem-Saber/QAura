"""TUI Screens for QAura — RunConfig, PlanApproval, PlanDetail."""

from textual.app import ComposeResult
from textual.screen import ModalScreen, Screen
from textual.containers import Vertical, Horizontal
from textual.widgets import Button, Input, Label, Static, TextArea, Markdown
from textual.message import Message


class RunConfigScreen(ModalScreen[dict | None]):
    """Modal form to configure a pipeline run."""

    class RunRequested(Message):
        def __init__(self, config: dict) -> None:
            self.config = config
            super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="run-config-dialog"):
            yield Static("Configure Pipeline Run", classes="title")
            yield Label("Requirements File Path:")
            yield Input(
                value="project_requirements.md",
                placeholder="path/to/requirements.md",
                id="input-requirements",
            )
            yield Label("Repository Path (optional):")
            yield Input(
                placeholder="/path/to/repo",
                id="input-repo",
            )
            yield Label("PR URL (optional):")
            yield Input(
                placeholder="https://github.com/org/repo/pull/123",
                id="input-pr-url",
            )
            with Horizontal(id="run-config-buttons"):
                yield Button("Start Run", variant="success", id="btn-start")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start":
            requirements = self.query_one("#input-requirements", Input).value
            repo_path = self.query_one("#input-repo", Input).value
            pr_url = self.query_one("#input-pr-url", Input).value
            self.dismiss(
                {
                    "requirements_path": requirements,
                    "repo_path": repo_path or None,
                    "pr_url": pr_url or None,
                }
            )
        else:
            self.dismiss(None)


class PlanApprovalScreen(ModalScreen[dict]):
    """Modal showing the test plan for approval/rejection."""

    def __init__(self, plan_text: str) -> None:
        super().__init__()
        self.plan_text = plan_text

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Static("Review Test Plan", classes="title")
            yield Markdown(self.plan_text, id="plan-summary")
            yield Label("Feedback (optional):")
            yield TextArea(id="feedback-area")
            with Horizontal(id="approval-buttons"):
                yield Button("Approve", variant="success", id="btn-approve")
                yield Button("Reject", variant="error", id="btn-reject")
                yield Button("View Full Plan", variant="primary", id="btn-detail")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        feedback = self.query_one("#feedback-area", TextArea).text
        if event.button.id == "btn-approve":
            self.dismiss({"approved": True, "feedback": feedback})
        elif event.button.id == "btn-reject":
            self.dismiss({"approved": False, "feedback": feedback})
        elif event.button.id == "btn-detail":
            self.app.push_screen(PlanDetailScreen(self.plan_text))


class PlanDetailScreen(Screen):
    """Full-screen Markdown viewer for the complete test plan."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, plan_text: str) -> None:
        super().__init__()
        self.plan_text = plan_text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Markdown(self.plan_text, id="plan-detail-content")
            with Horizontal(id="plan-detail-footer"):
                yield Button("Back", variant="default", id="btn-back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
