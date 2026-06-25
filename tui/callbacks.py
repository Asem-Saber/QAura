"""LangChain callback handler that pipes agent events to the TUI."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.agents import AgentAction, AgentFinish


class TUICallbackHandler(BaseCallbackHandler):
    """Forwards LangChain agent events to the TUI via post_message."""

    def __init__(self, post_fn) -> None:
        super().__init__()
        self._post = post_fn

    def _emit(self, text: str) -> None:
        from tui.app import PipelineLog
        try:
            self._post(PipelineLog(text))
        except Exception:
            pass

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs
    ) -> None:
        self._emit("[dim]LLM thinking...[/dim]")

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs
    ) -> None:
        tool_name = serialized.get("name", "unknown")
        display_input = input_str[:120] + "..." if len(input_str) > 120 else input_str
        self._emit(f"[cyan]🔧 Tool:[/cyan] [bold]{tool_name}[/bold]({display_input})")

    def on_tool_end(self, output: str, **kwargs) -> None:
        display = output[:200] + "..." if len(output) > 200 else output
        self._emit(f"[dim]   ↳ {display}[/dim]")

    def on_agent_action(self, action: AgentAction, **kwargs) -> None:
        self._emit(
            f"[yellow]⚡ Agent action:[/yellow] {action.tool}"
        )

    def on_agent_finish(self, finish: AgentFinish, **kwargs) -> None:
        self._emit("[green]✓ Agent finished[/green]")
