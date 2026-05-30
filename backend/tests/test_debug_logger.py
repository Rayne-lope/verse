from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import numpy as np
import pytest

from verse.config import AppConfig
from verse.persistence.debug_logger import DebugSessionLogger
from verse.orchestrator import Orchestrator
from verse.state import StateMachine
from verse.cli import list_sessions, show_session, replay_session


@pytest.fixture
def temp_session_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_debug_session_logger_initialization(temp_session_dir):
    logger = DebugSessionLogger(base_dir=temp_session_dir)
    assert logger.session_dir.exists()
    assert (logger.session_dir / "session.json").exists()

    with open(logger.session_dir / "session.json", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["session_id"] == logger.session_id
    assert "started_at" in meta
    assert meta["os"] == "macos"


def test_debug_session_logger_turns_and_files(temp_session_dir):
    logger = DebugSessionLogger(base_dir=temp_session_dir)
    turn_id = logger.new_turn()
    assert turn_id == 1
    turn_dir = logger.get_turn_dir(turn_id)
    assert turn_dir.exists()

    # Log audio
    logger.log_input_audio(turn_id, b"dummy_input_wav")
    assert (turn_dir / "input.wav").read_bytes() == b"dummy_input_wav"

    logger.log_output_audio(turn_id, b"dummy_output_wav")
    assert (turn_dir / "output.wav").read_bytes() == b"dummy_output_wav"

    # Log VAD timeline
    timeline = [{"timestamp": 123.45, "probability": 0.9, "state": "speech_active", "rms": 0.05}]
    logger.log_vad_timeline(turn_id, timeline)
    with open(turn_dir / "vad_timeline.jsonl", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == timeline[0]

    # Log pipeline events
    events = [{"timestamp": 123.46, "stage": "stt", "event": "started", "metadata": {}}]
    logger.log_pipeline_events(turn_id, events)
    with open(turn_dir / "pipeline_events.jsonl", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == events[0]

    # Log LLM transactions with redaction
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "system", "api_key": "secret123", "nested": {"password": "foo"}}
    ]
    response = {"text": "hi", "auth_token": "token123"}
    logger.log_llm_transaction(turn_id, messages, response)
    with open(turn_dir / "llm_transaction.json", encoding="utf-8") as f:
        trans = json.load(f)
    assert trans["messages"][0]["content"] == "hello"
    assert trans["messages"][1]["api_key"] == "[REDACTED]"
    assert trans["messages"][1]["nested"]["password"] == "[REDACTED]"
    assert trans["response"]["auth_token"] == "[REDACTED]"
    assert trans["response"]["text"] == "hi"

    # Log metrics
    metrics = {"stt_ms": 100, "llm_ms": 200, "tts_ms": 300}
    logger.log_metrics(turn_id, metrics)
    with open(turn_dir / "metrics.json", encoding="utf-8") as f:
        saved_metrics = json.load(f)
    assert saved_metrics == metrics

    # Log errors
    logger.log_error(turn_id, "ValueError", "something went wrong", "traceback_string")
    with open(turn_dir / "errors.jsonl", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    err = json.loads(lines[0])
    assert err["error_type"] == "ValueError"
    assert err["message"] == "something went wrong"
    assert err["traceback"] == "traceback_string"


@pytest.mark.anyio
async def test_orchestrator_integration_logging(temp_session_dir):
    logger = DebugSessionLogger(base_dir=temp_session_dir)

    # Mock components for Orchestrator
    stt = AsyncMock()
    stt.transcribe = AsyncMock(return_value=" Hello World ")
    llm = AsyncMock()
    response_mock = MagicMock()
    response_mock.text = "Hello to you too."
    response_mock.tool_calls = []
    llm.chat = AsyncMock(return_value=response_mock)
    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=b"synthetic_voice_wav")
    registry = MagicMock()
    registry.list_definitions.return_value = []
    state_machine = StateMachine()

    config = AppConfig()
    recorder = MagicMock()
    recorder.is_recording = False
    
    def start_rec(*args, **kwargs):
        recorder.is_recording = True
        
    recorder.start_recording = MagicMock(side_effect=start_rec)
    
    def stop_rec(*args, **kwargs):
        recorder.is_recording = False
        return b"fake_wav"
        
    recorder.stop_recording = MagicMock(side_effect=stop_rec)

    play_mock = MagicMock()

    orchestrator = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=state_machine,
        config=config,
        recorder=recorder,
        play=play_mock,
        debug_logger=logger,
    )

    # Start a turn
    orchestrator.start_listening()
    assert orchestrator._current_turn_id == 1

    # End the turn and handle pipeline
    with patch("verse.orchestrator._is_audio_too_short", return_value=False):
        await orchestrator.stop_and_respond()

    # Check files created in turn_001
    turn_dir = logger.get_turn_dir(1)
    assert (turn_dir / "input.wav").exists()
    assert (turn_dir / "output.wav").exists()
    assert (turn_dir / "metrics.json").exists()
    assert (turn_dir / "pipeline_events.jsonl").exists()
    assert (turn_dir / "llm_transaction.json").exists()

    # Read events to check if wrapped pipeline event collector worked
    with open(turn_dir / "pipeline_events.jsonl", encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    assert any(e["stage"] == "stt" and e["event"] == "started" for e in events)
    assert any(e["stage"] == "stt" and e["event"] == "completed" and e["metadata"].get("text") == "Hello World" for e in events)


def test_cli_subcommands(temp_session_dir, capsys):
    logger = DebugSessionLogger(base_dir=temp_session_dir)
    turn_id = logger.new_turn()
    logger.log_input_audio(turn_id, b"audio_in")
    logger.log_output_audio(turn_id, b"audio_out")
    logger.log_llm_transaction(turn_id, [{"role": "user", "content": "What is the time?"}], {"text": "It is 5 PM"})
    logger.log_metrics(turn_id, {"stt_ms": 150, "llm_ms": 250, "tts_ms": 350})

    # Test 'list' subcommand
    args = argparse.Namespace(dir=str(temp_session_dir))
    list_sessions(args)
    captured = capsys.readouterr().out
    assert logger.session_id in captured

    # Test 'show' subcommand
    args = argparse.Namespace(dir=str(temp_session_dir), session_id=logger.session_id)
    show_session(args)
    captured = capsys.readouterr().out
    assert "=== Session Metadata ===" in captured
    assert "turn_001" in captured
    assert "STT: 150ms" in captured

    # Test 'replay' subcommand
    args = argparse.Namespace(dir=str(temp_session_dir), session_id=logger.session_id, turn=1)
    replay_session(args)
    captured = capsys.readouterr().out
    assert "=== Replaying Session" in captured
    assert "What is the time?" in captured
    assert "It is 5 PM" in captured
    assert "Input Audio:" in captured
    assert "Output Audio:" in captured
