import asyncio
import time
from datetime import datetime, timezone

from langgraph.types import Command

from core.graph import graph, get_initial_state


class PipelineEvent:
    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data


class PipelineManager:
    def __init__(self):
        self._run_id: str | None = None
        self._config: dict | None = None
        self._queue: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()
        self._approval_event: asyncio.Event = asyncio.Event()
        self._approval_data: dict = {}
        self._running: bool = False
        self._phase: str = "idle"
        self._task: asyncio.Task | None = None
        self._agent_logs: dict[str, list[dict]] = {}
        self._current_agent: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_run_id(self) -> str | None:
        return self._run_id

    @property
    def current_phase(self) -> str:
        return self._phase

    @property
    def current_agent(self) -> str | None:
        return self._current_agent

    def start_run(self, requirements_path: str | None) -> str:
        if self._running:
            raise RuntimeError("A pipeline run is already in progress")

        run_id = f"qaura_run_{int(time.time())}"
        self._run_id = run_id
        self._config = {"configurable": {"thread_id": run_id}}
        self._queue = asyncio.Queue()
        self._approval_event = asyncio.Event()
        self._approval_data = {}
        self._running = True
        self._phase = "initializing"
        self._agent_logs = {}

        initial_state = get_initial_state(requirements_path)
        self._task = asyncio.create_task(self._run(initial_state))
        return run_id

    async def _run(self, initial_state: dict):
        try:
            self._push("phase_change", {"phase": "Phase 1: Planning", "agent_name": "test_architect", "status": "running"})

            async for event in graph.astream(
                initial_state, config=self._config, stream_mode="updates", subgraphs=True,
            ):
                self._process_stream_event(event)

            state = graph.get_state(self._config)
            state_values = state.values

            if state_values.get("test_plan") and state.next:
                self._phase = "awaiting_approval"
                plan = state_values["test_plan"]
                plan_data = plan.model_dump() if hasattr(plan, "model_dump") else plan
                self._push("plan_ready", {"plan": plan_data})

                self._approval_event.clear()
                await self._approval_event.wait()

                approved = self._approval_data.get("approved", False)
                feedback = self._approval_data.get("feedback", "")

                if approved:
                    self._push("phase_change", {"phase": "Phase 2: Generation", "agent_name": "unit_test_gen", "status": "running"})
                else:
                    self._push("agent_log", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "agent": "human_approval",
                        "message": "Plan rejected by operator.",
                        "tool_calls": [],
                    })

                async for event in graph.astream(
                    Command(resume={"approved": approved, "feedback": feedback}),
                    config=self._config,
                    stream_mode="updates",
                    subgraphs=True,
                ):
                    self._process_stream_event(event)

            final_state = graph.get_state(self._config).values
            self._phase = "complete"
            self._current_agent = None
            agent_events = {k: len(v) for k, v in self._agent_logs.items()}
            self._push("stats_update", {
                "run_id": self._run_id,
                "phase": self._phase,
                "stats": self._serialize(final_state.get("execution_summary")),
                "agent_events": agent_events,
            })
            self._push("run_complete", {
                "execution_summary": self._serialize(final_state.get("execution_summary")),
                "qa_report": self._serialize(final_state.get("qa_report")),
            })
        except Exception as e:
            self._phase = "errored"
            self._current_agent = None
            self._push("agent_log", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": "system",
                "message": f"Pipeline error: {e}",
                "tool_calls": [],
            })
            self._push("run_complete", {})
        finally:
            self._running = False
            await self._queue.put(None)

    def _process_stream_event(self, event):
        namespace, update = event
        ts = datetime.now(timezone.utc).isoformat()

        if namespace:
            agent_name = namespace[0]
            for node_name, node_update in update.items():
                if node_name == "agent":
                    messages = node_update.get("messages", [])
                    if messages:
                        last_msg = messages[-1]
                        tool_calls = []
                        message_text = "Agent provided a response."
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            tool_calls = [{"name": tc["name"]} for tc in last_msg.tool_calls]
                            message_text = f"Calling tools: {[tc['name'] for tc in tool_calls]}"
                        self._push("agent_log", {
                            "timestamp": ts,
                            "agent": agent_name,
                            "message": message_text,
                            "tool_calls": tool_calls,
                        })
                        if agent_name not in self._agent_logs:
                            self._agent_logs[agent_name] = []
                        self._agent_logs[agent_name].append({
                            "timestamp": ts,
                            "agent": agent_name,
                            "message": message_text,
                            "tool_calls": tool_calls,
                        })
                elif node_name == "tools":
                    self._push("agent_log", {
                        "timestamp": ts,
                        "agent": agent_name,
                        "message": "Tool execution finished.",
                        "tool_calls": [],
                    })
                    if agent_name not in self._agent_logs:
                        self._agent_logs[agent_name] = []
                    self._agent_logs[agent_name].append({
                        "timestamp": ts,
                        "agent": agent_name,
                        "message": "Tool execution finished.",
                        "tool_calls": [],
                    })
        else:
            for node_name in update.keys():
                if node_name == "__metadata__":
                    continue
                phase_map = {
                    "test_architect": "Phase 1: Planning",
                    "human_approval": "Phase 1: Approval",
                    "unit_test_gen": "Phase 2: Unit Tests",
                    "integration_test_gen": "Phase 2: Integration Tests",
                    "e2e_gen": "Phase 2: E2E Tests",
                    "execution_agent": "Phase 3: Execution",
                    "reporting_agent": "Phase 4: Reporting",
                    "defect_intelligence_agent": "Phase 4: Defect Analysis",
                    "self_healing_agent": "Phase 5: Self-Healing",
                }
                self._phase = phase_map.get(node_name, node_name)
                self._current_agent = node_name
                self._push("phase_change", {
                    "phase": self._phase,
                    "agent_name": node_name,
                    "status": "completed",
                })
                agent_events = {k: len(v) for k, v in self._agent_logs.items()}
                self._push("stats_update", {
                    "run_id": self._run_id,
                    "phase": self._phase,
                    "agent_events": agent_events,
                })

    def _push(self, event_type: str, data: dict):
        self._queue.put_nowait(PipelineEvent(event_type, data))

    def _serialize(self, obj):
        if obj is None:
            return None
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return obj

    async def get_event_stream(self, run_id: str):
        if run_id != self._run_id:
            return
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    def get_agent_logs(self, agent_name: str) -> list[dict]:
        return self._agent_logs.get(agent_name, [])

    def get_all_agent_names(self) -> list[str]:
        return list(self._agent_logs.keys())

    def get_run_state(self, run_id: str) -> dict | None:
        if run_id != self._run_id or self._config is None:
            return None
        try:
            return graph.get_state(self._config).values
        except Exception:
            return None

    def approve_run(self, run_id: str, approved: bool, feedback: str = ""):
        if run_id != self._run_id:
            raise ValueError(f"No active run with id {run_id}")
        self._approval_data = {"approved": approved, "feedback": feedback}
        self._approval_event.set()


pipeline_manager = PipelineManager()
