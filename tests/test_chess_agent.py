"""Fast, offline tests for the student-implemented chess tool."""

import json

import httpx
import pytest
from openai.types.chat import ChatCompletion

from assignment.agent import ChessAgent
from assignment.agent.chess_agent import format_chess_state
from assignment.agent.tools import PLAY_MOVE_TOOL


INITIAL_STATE = {
    "status": "White to move",
    "turn": "white",
    "in_check": False,
    "game_over": False,
    "fen": "initial-fen",
    "squares": {"e1": "K", "e2": "P", "e7": "p", "e8": "k"},
    "history": [],
    "legal_moves": ["e2e4", "d2d4"],
    "human_move": None,
    "engine_move": None,
}

UPDATED_STATE = {
    **INITIAL_STATE,
    "fen": "updated-fen",
    "history": [
        {"ply": 1, "san": "e4", "uci": "e2e4"},
        {"ply": 2, "san": "e5", "uci": "e7e5"},
    ],
    "legal_moves": ["g1f3", "f1c4"],
    "human_move": "e2e4",
    "engine_move": "e7e5",
}


class FakeChessEnvironment:
    cwd = "/testbed"
    server_url = "http://chess.test"
    system, release, version, machine = "Linux", "6.1", "#1", "x86_64"

    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


@pytest.fixture
def chess_client():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/reset" and request.method == "POST":
            return httpx.Response(200, json=INITIAL_STATE)
        if request.url.path == "/api/state" and request.method == "GET":
            return httpx.Response(200, json=INITIAL_STATE)
        if request.url.path == "/api/move" and request.method == "POST":
            if json.loads(request.content) == {"move": "e2e4"}:
                return httpx.Response(200, json=UPDATED_STATE)
            return httpx.Response(400, json={"detail": "illegal move"})
        return httpx.Response(404, json={"detail": "not found"})

    client = httpx.Client(
        base_url="http://chess.test",
        transport=httpx.MockTransport(handler),
    )
    client.requests = requests
    yield client
    client.close()


@pytest.fixture
def make_agent(monkeypatch, chess_client):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://model.test/v1")
    return ChessAgent(
        FakeChessEnvironment(),
        model="test-model",
        http_client=chess_client,
        auto_stop_environment=False,
    )


def tool_call(move: str, call_id: str = "move_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "play_move",
            "arguments": json.dumps({"move": move}),
        },
    }


def test_play_move_schema_is_strict_and_registered(make_agent):
    function = PLAY_MOVE_TOOL["function"]
    parameters = function["parameters"]

    assert PLAY_MOVE_TOOL["type"] == "function"
    assert function["name"] == "play_move"
    assert function["strict"] is True
    assert parameters["properties"]["move"]["type"] == "string"
    assert parameters["required"] == ["move"]
    assert parameters["additionalProperties"] is False
    assert make_agent.tools == [PLAY_MOVE_TOOL]


def test_initial_prompt_contains_board_and_legal_moves(make_agent):
    prompt = json.dumps(make_agent.build_prompt())
    assert "a b c d e f g h" in prompt
    assert "legal_moves" in prompt
    assert "e2e4" in prompt


def test_board_only_formatter_omits_legal_moves_without_losing_position():
    observation = format_chess_state(INITIAL_STATE, include_legal_moves=False)

    assert "a b c d e f g h" in observation
    assert "fen: initial-fen" in observation
    assert "legal_moves:" not in observation
    assert "e2e4" not in observation


def test_play_move_posts_request_and_returns_new_state(make_agent, chess_client):
    messages = make_agent.execute_tool_calls([tool_call("e2e4")])

    move_request = chess_client.requests[-1]
    assert move_request.method == "POST"
    assert move_request.url.path == "/api/move"
    assert json.loads(move_request.content) == {"move": "e2e4"}
    assert messages[0]["tool_call_id"] == "move_1"
    assert "engine_move: e7e5" in messages[0]["content"]
    assert "legal_moves: g1f3 f1c4" in messages[0]["content"]
    assert make_agent.last_state == UPDATED_STATE
    assert make_agent.finished is False


def test_rejected_and_malformed_moves_are_recoverable(make_agent):
    rejected = make_agent.execute_tool_calls([tool_call("e2e5")])
    malformed_call = tool_call("e2e4", "move_2")
    malformed_call["function"]["arguments"] = "{not json"
    malformed = make_agent.execute_tool_calls([malformed_call])

    assert "<chess_error>" in rejected[0]["content"]
    assert "<chess_error>" in malformed[0]["content"]
    assert make_agent.finished is False


def test_chess_loop_recovers_from_text_and_stops_on_terminal_move(make_agent, monkeypatch):
    monkeypatch.setitem(UPDATED_STATE, "game_over", True)
    responses = [
        {"role": "assistant", "content": "I choose e2e4."},
        {"role": "assistant", "content": "", "tool_calls": [tool_call("e2e4")]},
    ]
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        message = responses[len(requests) - 1]
        return ChatCompletion.model_validate({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                "message": message,
            }],
        })

    make_agent.client.chat.completions.create = create
    make_agent.run()

    assert len(requests) == 2
    assert requests[1]["tool_choice"] == "required"
    assert make_agent.history[0]["content"] == "I choose e2e4."
    assert make_agent.finished is True
    assert make_agent.last_state["game_over"] is True


@pytest.mark.parametrize("disconnected", [False, True])
def test_move_error_refreshes_terminal_state_and_stops_loop(make_agent, disconnected):
    terminal_state = {**UPDATED_STATE, "game_over": True, "legal_moves": [], "status": "Draw"}
    requests = []
    model_calls = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/move":
            if disconnected:
                raise httpx.ReadError("Server disconnected after committing the move.", request=request)
            return httpx.Response(400, json={"detail": "The game is over. Start a new game to continue."})
        return httpx.Response(200, json=terminal_state)

    def create(**kwargs):
        model_calls.append(kwargs)
        assert len(model_calls) == 1, "No model request should follow a terminal board."
        return ChatCompletion.model_validate({
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": "", "tool_calls": [tool_call("e2e4")],
            }}],
        })

    make_agent.client.chat.completions.create = create
    with httpx.Client(base_url="http://chess.test", transport=httpx.MockTransport(handler)) as client:
        make_agent.chess_client = client
        make_agent.run()

    assert requests == [("POST", "/api/move"), ("GET", "/api/state")]
    assert make_agent.last_state == terminal_state
    assert make_agent.finished is True
    assert "<chess_error>" in make_agent.history[-1]["content"]
    assert "game_over: True" in make_agent.history[-1]["content"]


def test_terminal_error_text_does_not_override_active_server_state(make_agent):
    def handler(request):
        if request.url.path == "/api/move":
            return httpx.Response(400, json={"detail": "The game is over."})
        return httpx.Response(200, json=INITIAL_STATE)

    with httpx.Client(base_url="http://chess.test", transport=httpx.MockTransport(handler)) as client:
        make_agent.chess_client = client
        observation = make_agent.execute_tool_calls([tool_call("e2e4")])[0]

    assert "The game is over." in observation["content"]
    assert "game_over: False" in observation["content"]
    assert make_agent.finished is False


def test_failed_refresh_preserves_original_move_error(make_agent):
    def handler(request):
        if request.url.path == "/api/move":
            return httpx.Response(400, json={"detail": "illegal move"})
        raise httpx.ConnectError("Server unavailable.", request=request)

    with httpx.Client(base_url="http://chess.test", transport=httpx.MockTransport(handler)) as client:
        make_agent.chess_client = client
        observation = make_agent.execute_tool_calls([tool_call("e2e4")])[0]

    assert "illegal move" in observation["content"]
    assert "Could not refresh the live board" in observation["content"]
    assert make_agent.last_state == INITIAL_STATE
    assert make_agent.finished is False
