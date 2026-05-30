from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_SESSIONS_DIR = Path("~/.verse/debug_sessions").expanduser()


def list_sessions(args: argparse.Namespace) -> None:
    sessions_dir = Path(args.dir).expanduser()
    if not sessions_dir.exists():
        print("No debug sessions found.")
        return

    sessions = []
    for p in sessions_dir.iterdir():
        if p.is_dir() and (p / "session.json").exists():
            try:
                with open(p / "session.json", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["path"] = p
                meta["id"] = p.name
                sessions.append(meta)
            except Exception:
                pass

    if not sessions:
        print("No debug sessions found.")
        return

    sessions.sort(key=lambda s: s.get("started_at", 0), reverse=True)

    print(f"{'Session ID':<45} | {'Started At':<25} | {'OS':<10}")
    print("-" * 88)
    for s in sessions:
        started_val = s.get("started_at", 0)
        try:
            started_str = datetime.fromtimestamp(started_val).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception:
            started_str = str(started_val)
        print(f"{s['id']:<45} | {started_str:<25} | {s.get('os', 'unknown'):<10}")


def show_session(args: argparse.Namespace) -> None:
    sessions_dir = Path(args.dir).expanduser()
    session_path = sessions_dir / args.session_id
    if not session_path.exists() or not session_path.is_dir():
        print(f"Error: Session {args.session_id} not found.")
        sys.exit(1)

    session_json = session_path / "session.json"
    if session_json.exists():
        with open(session_json, encoding="utf-8") as f:
            meta = json.load(f)
        print("=== Session Metadata ===")
        for k, v in meta.items():
            if k == "started_at":
                try:
                    v = datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            print(f"{k}: {v}")

    turns = []
    for p in session_path.iterdir():
        if p.is_dir() and p.name.startswith("turn_"):
            turns.append(p.name)
    turns.sort()

    print(f"\n=== Turns ({len(turns)}) ===")
    for turn in turns:
        turn_dir = session_path / turn
        metrics_file = turn_dir / "metrics.json"
        metrics_str = ""
        if metrics_file.exists():
            try:
                with open(metrics_file, encoding="utf-8") as f:
                    metrics = json.load(f)
                metrics_str = f" [STT: {metrics.get('stt_ms')}ms, LLM: {metrics.get('llm_ms')}ms, TTS: {metrics.get('tts_ms')}ms]"
            except Exception:
                pass

        err_file = turn_dir / "errors.jsonl"
        err_str = " (⚠️ ERROR)" if err_file.exists() else ""

        trans_file = turn_dir / "llm_transaction.json"
        transcript_str = ""
        if trans_file.exists():
            try:
                with open(trans_file, encoding="utf-8") as f:
                    trans = json.load(f)
                msgs = trans.get("messages", [])
                user_msg = next(
                    (
                        m.get("content")
                        for m in reversed(msgs)
                        if m.get("role") == "user"
                    ),
                    "",
                )
                if user_msg:
                    transcript_str = f' - "{user_msg}"'
            except Exception:
                pass

        print(f"- {turn}{metrics_str}{err_str}{transcript_str}")


def replay_session(args: argparse.Namespace) -> None:
    sessions_dir = Path(args.dir).expanduser()
    session_path = sessions_dir / args.session_id
    if not session_path.exists() or not session_path.is_dir():
        print(f"Error: Session {args.session_id} not found.")
        sys.exit(1)

    print(f"=== Replaying Session {args.session_id} ===")

    turns = []
    for p in session_path.iterdir():
        if p.is_dir() and p.name.startswith("turn_"):
            turns.append(p.name)
    turns.sort()

    if args.turn:
        turn_name = f"turn_{args.turn:03d}"
        if turn_name not in turns:
            print(f"Error: Turn {turn_name} not found in this session.")
            sys.exit(1)
        turns = [turn_name]

    for turn in turns:
        turn_dir = session_path / turn
        print(f"\n--- {turn} ---")

        trans_file = turn_dir / "llm_transaction.json"
        if trans_file.exists():
            try:
                with open(trans_file, encoding="utf-8") as f:
                    trans = json.load(f)
                for msg in trans.get("messages", []):
                    role = msg.get("role", "unknown").upper()
                    content = msg.get("content", "")
                    if msg.get("tool_calls"):
                        print(f"[{role}]: (Tool Calls: {msg.get('tool_calls')})")
                    else:
                        print(f"[{role}]: {content}")
                print(f"[ASSISTANT]: {trans.get('response', {}).get('text', '')}")
            except Exception as e:
                print(f"Could not read transaction: {e}")

        input_wav = turn_dir / "input.wav"
        output_wav = turn_dir / "output.wav"
        if input_wav.exists():
            print(f"🔊 Input Audio: {input_wav}")
        if output_wav.exists():
            print(f"🔊 Output Audio: {output_wav}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verse Debug Session Replay Lab CLI"
    )
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_SESSIONS_DIR),
        help="Directory of debug sessions",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all debug sessions")

    show_parser = subparsers.add_parser(
        "show", help="Show details of a debug session"
    )
    show_parser.add_argument("session_id", help="Session ID")

    replay_parser = subparsers.add_parser("replay", help="Replay a debug session")
    replay_parser.add_argument("session_id", help="Session ID")
    replay_parser.add_argument(
        "--turn", type=int, help="Optional turn index to replay"
    )

    args = parser.parse_args()
    if args.command == "list":
        list_sessions(args)
    elif args.command == "show":
        show_session(args)
    elif args.command == "replay":
        replay_session(args)


if __name__ == "__main__":
    main()
