"""Audit assignment evidence and build an explicitly complete or partial ZIP.

Usage: uv run python scripts/prepare_submission.py --allow-incomplete
Replay: uv run --with chess==1.11.2 python scripts/prepare_submission.py --replay-chess --allow-incomplete
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ARTIFACTS = (
    "fix.patch", "part1-trajectory.json", "django__django-15368.patch",
    "django__django-15368-trajectory.json", "token-usage-analysis.md",
    "part3-trajectory.json", "game-result.json",
    "part3-no-legal-moves-deepseek.json", "part3-no-legal-moves-deepseek-result.json",
    "part3-legal-moves-deepseek.json", "part3-legal-moves-deepseek-result.json",
    "part3-no-legal-moves-gpt-oss.json", "part3-no-legal-moves-gpt-oss-result.json",
    "part3-legal-moves-gpt-oss.json", "part3-legal-moves-gpt-oss-result.json",
    "observation-experiment.md", "part3-python-skill-trajectory.json",
)
CHESS_RUNS = (
    ("part3-trajectory.json", "game-result.json", True),
    ("part3-no-legal-moves-deepseek.json", "part3-no-legal-moves-deepseek-result.json", False),
    ("part3-legal-moves-deepseek.json", "part3-legal-moves-deepseek-result.json", True),
    ("part3-no-legal-moves-gpt-oss.json", "part3-no-legal-moves-gpt-oss-result.json", False),
    ("part3-legal-moves-gpt-oss.json", "part3-legal-moves-gpt-oss-result.json", True),
)


def read_json(name: str) -> dict:
    return json.loads((ROOT / "artifacts" / name).read_text())


def validate_prompt(prompt: list[dict]) -> None:
    assert len(prompt) >= 2 and prompt[0]["role"] == "system" and prompt[1]["role"] == "user"
    pending = []
    for message in prompt:
        if message["role"] == "tool":
            assert message["tool_call_id"] in pending, "Unlinked tool observation"
            pending.remove(message["tool_call_id"])
        else:
            assert not pending, "Incomplete assistant tool action"
            if message["role"] == "assistant":
                pending = [call["id"] for call in message.get("tool_calls") or []]
    assert not pending, "Prompt ends with unanswered tool calls"


def audit_trajectory(data: dict) -> None:
    prompts, responses = data["prompts"], data["responses"]
    assert responses and len(prompts) == len(responses), "Run includes an unanswered model request"
    for prompt in prompts:
        validate_prompt(prompt)
        assert prompt[:2] == prompts[0][:2], "Original instructions changed"
    for event in data.get("compactions", []):
        validate_prompt(event["active_prompt_before"])
        assert event["estimated_tokens_after"] < event["estimated_tokens_before"]


def linked_observations(data: dict, step: int) -> list[dict]:
    if step + 1 == len(data["prompts"]):
        return []  # The provided logger saves prompts, not the final observation.
    next_prompt = data["prompts"][step + 1]
    position = max(i for i, m in enumerate(next_prompt) if m["role"] == "assistant")
    previous_calls = data["responses"][step]["choices"][0]["message"].get("tool_calls") or []
    retained_calls = next_prompt[position].get("tool_calls") or []
    assert [(c["id"], c["function"]) for c in retained_calls] == [(c["id"], c["function"]) for c in previous_calls]
    # IDs may repeat between steps. Match only within this assistant action.
    return [m for m in next_prompt[position + 1:] if m["role"] == "tool"]


def observation_statistics(data: dict, result: dict) -> dict:
    total, illegal = 0, 0
    for step, response in enumerate(data["responses"]):
        calls = response["choices"][0]["message"].get("tool_calls") or []
        observations = linked_observations(data, step) if calls else []
        for call in calls:
            if call["function"]["name"] != "play_move":
                continue
            total += 1
            observation = next((m["content"] for m in observations if m["tool_call_id"] == call["id"]), "")
            if "<chess_error>" in observation and re.search(r"not legal|illegal move", observation, re.I):
                illegal += 1
    last = data["responses"][-1]["choices"][0]["message"].get("tool_calls") or []
    assert len(last) == 1 and last[0]["function"]["name"] == "play_move"
    assert result.get("game_over") is True, "Direct chess run did not finish"
    # Final success is corroborated by result/history and optional replay.
    final_move = json.loads(last[0]["function"]["arguments"])["move"].strip().lower()
    assert result["human_move"] == final_move, "Final call and result disagree"
    return {
        "model": data["responses"][0]["model"],
        "action_requests": len(data["responses"]), "play_move_calls": total,
        "illegal_calls": illegal, "invalid_move_rate": illegal / total if total else 0,
        "game_over": result["game_over"], "status": result["status"],
        "plies": len(result["history"]), "compactions": len(data.get("compactions", [])),
        "length_responses": sum(r["choices"][0]["finish_reason"] == "length" for r in data["responses"]),
    }


def patched_game_class(directory: Path):
    task = read_json_from_path(ROOT / "tasks/chess-terminal-move/task.json")
    target = directory / "src/chess_app/game.py"
    target.parent.mkdir(parents=True)
    source = subprocess.check_output(["git", "-C", str(ROOT / "chess_app"), "show", f"{task['base_commit']}:src/chess_app/game.py"])
    target.write_bytes(source)
    subprocess.run(["git", "apply", str(ROOT / "artifacts/fix.patch")], cwd=directory, check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location("submission_replay_game", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ChessGame, module.InvalidMoveError


def read_json_from_path(path: Path) -> dict:
    return json.loads(path.read_text())


def replay_moves(data: dict, result: dict, game_class, invalid_error) -> int:
    game, rejected = game_class(), 0
    for step, response in enumerate(data["responses"]):
        live_action = False
        observations = linked_observations(data, step)
        for call in response["choices"][0]["message"].get("tool_calls") or []:
            assert call["function"]["name"] == "play_move", "Replay expects direct moves only"
            if live_action:
                continue
            live_action = True
            arguments = json.loads(call["function"]["arguments"])
            assert set(arguments) == {"move"} and isinstance(arguments["move"], str)
            observation = next((m["content"] for m in observations if m["tool_call_id"] == call["id"]), "")
            if "<chess_error>" in observation and not re.search(r"not legal|illegal move", observation, re.I):
                # A transport failure is not an illegal move. Commit it only
                # if a refreshed observation proves that the board changed.
                observed_fen = re.search(r"\nfen: ([^\n]+)", observation)
                if observed_fen is None or observed_fen.group(1) == game.state()["fen"]:
                    continue
            try:
                game.play_human_move(arguments["move"])
            except invalid_error as exc:
                assert re.search(r"not legal", str(exc)), str(exc)
                rejected += 1
    # Ignore the response-only human_state wrapper; compare every state field.
    for key, value in game.state().items():
        assert result[key] == value, f"Replay differs in {key}"
    return rejected


def audit_skill(data: dict) -> int:
    skill_loaded, snippets = False, 0
    for step, response in enumerate(data["responses"]):
        for call in response["choices"][0]["message"].get("tool_calls") or []:
            function = call["function"]
            if function["name"] == "invoke_skill":
                assert json.loads(function["arguments"]) == {"name": "select-move"}
                observations = linked_observations(data, step)
                assert any("# Step 3:" in m["content"] for m in observations)
                skill_loaded = True
            elif function["name"] == "run_python":
                assert skill_loaded, "Python search preceded skill loading"
                tree = ast.parse(json.loads(function["arguments"])["code"])
                names = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
                assert "simulate_move" in names and names.count("play_move") == 1
                snippets += 1
                for message in linked_observations(data, step):
                    raw, _, state = message["content"].partition("\n\n<chess_state>")
                    output = json.loads(raw)
                    assert output["error"] is None and state, "Snippet failed or board was not refreshed"
    assert snippets, "No programmatic search and commitment evidence"
    return snippets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--replay-chess", action="store_true")
    args = parser.parse_args()
    files = [ROOT / "artifacts" / name for name in REQUIRED_ARTIFACTS]
    files += sorted((ROOT / "src/assignment/agent").glob("*.py"))
    files += [ROOT / "src/assignment/prompts.py", ROOT / "AI_USAGE.md"]
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    # Include the evidence linked by reports, while excluding unrelated failed
    # attempts, secrets, tests, task files, and submodule contents.
    optional = (
        "django__django-15368-baseline.patch", "django__django-15368-baseline-trajectory.json",
        "django__django-15368-baseline-check.log", "django__django-15368-check.log",
        "part1-check.log", "part3-python-skill-result.json", "part3-python-skill-run.log",
        "submission-audit.json",
        "part3-no-legal-moves-deepseek-run.log",
    )
    files += [ROOT / "artifacts" / name for name in optional if (ROOT / "artifacts" / name).is_file()]
    for name in ("part1-trajectory.json", "django__django-15368-trajectory.json", "part3-python-skill-trajectory.json"):
        if (ROOT / "artifacts" / name).is_file():
            audit_trajectory(read_json(name))
    statistics = {}
    with tempfile.TemporaryDirectory(prefix="assignment-replay-") as tmp:
        if args.replay_chess:
            game_class, invalid_error = patched_game_class(Path(tmp))
        for trajectory, result_name, include_legal in CHESS_RUNS:
            if not all((ROOT / "artifacts" / name).is_file() for name in (trajectory, result_name)):
                continue
            data, result = read_json(trajectory), read_json(result_name)
            audit_trajectory(data)
            for prompt in data["prompts"]:
                for message in prompt:
                    if "<chess_state>" in (message.get("content") or ""):
                        assert ("legal_moves:" in message["content"]) == include_legal
            stats = observation_statistics(data, result)
            if args.replay_chess:
                assert replay_moves(data, result, game_class, invalid_error) == stats["illegal_calls"]
                stats["replay_verified"] = True
            statistics[trajectory] = stats
    skill_path = ROOT / "artifacts/part3-python-skill-trajectory.json"
    if skill_path.is_file():
        snippets = audit_skill(read_json(skill_path.name))
        print(f"Skill evidence: {snippets} Python search/commit snippets")
    print(json.dumps({"statistics": statistics, "missing": missing}, indent=2))
    (ROOT / "artifacts/submission-audit.json").write_text(json.dumps({"statistics": statistics, "missing": missing}, indent=2) + "\n")
    if missing and not args.allow_incomplete:
        raise SystemExit("Missing evidence; no ZIP written. Use --allow-incomplete to build a partial archive.")
    present = [p for p in files if p.is_file()]
    for path in present:
        assert not re.search(rb"\bsk-[A-Za-z0-9_-]{16,}", path.read_bytes()), f"Possible credential in {path.name}; no ZIP written"
    output = ROOT / "artifacts" / ("assignment-1-partial.zip" if missing else "assignment-1.zip")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in present:
            archive.write(path, str(path.relative_to(ROOT)))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
    print(f"{'Partial' if missing else 'Complete'} archive: {output}")


if __name__ == "__main__":
    main()
