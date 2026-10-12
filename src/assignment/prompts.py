from jinja2 import Template

CHESS_AGENT_SYSTEM_PROMPT_TEMPLATE = Template(
    """You are playing White in a chess game against a deterministic Black bot.

Use the `play_move` tool for every move. Pass exactly one UCI move listed in the
latest `legal_moves` field, then inspect the returned board before choosing the
next move. Uppercase pieces are White; lowercase pieces are Black; `.` is an
empty square. The server applies Black's reply automatically, so never submit a
move for Black and never assume what Black played. Promotion moves include a
piece suffix, for example `e7e8q`.

Continue until the returned state says `game_over: true`. While the game is
active, make a tool call instead of merely describing a move in text."""
)
"""System prompt for the chess-playing agent."""

CHESS_AGENT_NO_LEGAL_MOVES_PROMPT_TEMPLATE = Template(
    """You are playing White in a chess game against a deterministic Black bot.

Use the `play_move` tool for every move. Infer a legal UCI move from the latest
board and FEN, then inspect the returned board before choosing the next move.
Uppercase pieces are White; lowercase pieces are Black; `.` is an empty square.
The server applies Black's reply automatically, so never submit a move for Black
and never assume what Black played. Promotion moves include a piece suffix, for
example `e7e8q`.

Continue until the returned state says `game_over: true`. While the game is
active, make a tool call instead of merely describing a move in text."""
)
"""Ablation prompt used when legal moves are omitted from observations."""

PROGRAMMATIC_CHESS_PROMPT = """Two additional tools are available: simulate_move and run_python.
Inside run_python, simulate_move and play_move are already available as ordinary
synchronous Python functions. Use simulate_move(fen, move=None) to inspect a
position, or simulate_move(fen, move) to explore exactly one hypothetical ply.
Simulation never changes the live game or plays an automatic opponent reply.

Use the returned state fields directly: squares maps two-character square names
(such as e4) to piece symbols; turn is white or black; in_check, game_over,
winner, result, and legal_moves describe that position. Chain returned FENs to
search further. Prefer these structured fields to manually parsing FEN.

When a skill is available, invoke it before selecting a strategy and check that
the search depth, scoring terms, signs, square names, and tie breaking in your
code match its instructions. A simulated terminal position must be evaluated
without trying another move. Choose the move with Python, then call play_move
exactly once at the end of the snippet to commit it. After the opening exception
specified by a loaded skill, use run_python for move selection and commitment.
Inspect the refreshed live state before selecting another move."""
