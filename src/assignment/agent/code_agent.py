"""The Part 1 coding agent: fix a software issue and submit a git patch."""

from __future__ import annotations

import json
from typing import Any

from assignment.agent.base import (
    DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
    DEFAULT_COMPACTION_MAX_TOKENS,
    Agent,
    format_tool_output,
)
from assignment.agent.tools import EXECUTE_TOOL, SEND_MESSAGE_TOOL
from assignment.env import Environment

class CodeAgent(Agent):
    """An agent that fixes a software issue and submits a git patch."""

    def __init__(
        self,
        task: str,
        environment: Environment,
        model: str | None = None,
        logs_save_path: str | None = None,
        step_limit: int = 100,
        skills_path: str | None = None,
        auto_stop_environment: bool = True,
        compact_threshold_tokens: int | None = None,
        compaction_keep_recent_steps: int = DEFAULT_COMPACTION_KEEP_RECENT_STEPS,
        compaction_max_tokens: int = DEFAULT_COMPACTION_MAX_TOKENS,
    ):
        super().__init__(
            environment=environment,
            model=model,
            logs_save_path=logs_save_path,
            step_limit=step_limit,
            skills_path=skills_path,
            auto_stop_environment=auto_stop_environment,
            compact_threshold_tokens=compact_threshold_tokens,
            compaction_keep_recent_steps=compaction_keep_recent_steps,
            compaction_max_tokens=compaction_max_tokens,
        )
        self.task = task
        self.submitted_patch = ""

        # TODO(Part 1.3): Make the `execute` and `send_message` tools available
        # to the agent.
        self.tools.extend([EXECUTE_TOOL, SEND_MESSAGE_TOOL])

        # TODO(1.1.b): Construct the system prompt and task_prompt. These
        # should be usable by the `Agent.build_prompt` method.
        self.task_prompt = task
        system_information = {
            "machine": self.env.machine,
            "release": self.env.release,
            "system": self.env.system,
            "version": self.env.version,
        }
        self.system_prompt = f"""You are a coding agent solving a software issue.Inspect the repository and reproduce the reported problem before editing.
    Use the provided tools to make changes and run relevant tests.
    Base your conclusions on tool results, and report failures accurately.
<system_information>
    {json.dumps(system_information, indent=2)}
</system_information>
    """
        # TODO(1.4): If any skills are available to the agent, make their
        # descriptions/metadata available to the agent in the prompt.
        if self.skills:
            metadata_parts = []

            for skill in self.skills.values():
                metadata_parts.append(skill["metadata"])

            catalog = "\n\n".join(metadata_parts)

            self.system_prompt += (
                "\n\nAvailable skills:\n"
                f"{catalog}\n\n"
                "Use invoke_skill with the skill name to read its full instructions "
                "before starting work covered by that skill."
            )

    def execute_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Execute ``execute`` and ``send_message`` calls in the code sandbox."""

        # TODO(Part 1.3): Parse each call, execute recognized tools, and return
        # one message per call (there may be multiple tool calls in one agent
        # response!). Malformed JSON and unknown tools must become recoverable
        # observations relayed to the agent instead of exceptions.
        observations = []
        for call in tool_calls:
            call_id = call["id"]
            function = call["function"]
            name = function["name"]
            raw_arguments = function["arguments"]
            observation = {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "",
            }
            if self.finished:
                observation["content"] = (
                    "Task already submitted; no further actions are allowed."
                )
                observations.append(observation)
                continue

            try:
                arguments = json.loads(raw_arguments)

                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
            except (ValueError, TypeError) as exc:
                observation["content"] = f"Invalid tool arguments: {exc}"
                observations.append(observation)
                continue
            if name == "execute":
                try:
                    result = self.env.execute(**arguments)
                    observation["content"] = format_tool_output(result)
                except (TypeError, ValueError) as exc:
                    observation["content"] = f"Invalid execute arguments: {exc}"
            elif name == "send_message":
                summary = arguments.get("summary")
                if set(arguments) != {"summary"} or not isinstance(summary, str):
                    observation["content"] = (
                        "send_message requires exactly one string argument: summary."
                    )
                else:
                    print(summary)
                    self.finished = True
                    observation["content"] = "Submission received."
            elif name == "invoke_skill" and self.skills:
                skill_name = arguments.get("name")
                if set(arguments) != {"name"} or not isinstance(skill_name, str):
                    observation["content"] = (
                        "invoke_skill requires exactly one string argument: name."
                    )
                elif skill_name not in self.skills:
                    observation["content"] = f"Unknown skill: {skill_name}"
                else:
                    observation["content"] = self.skills[skill_name]["content"]
            else:
                observation["content"] = f"Unknown tool: {name}"

            observations.append(observation)
        return observations
