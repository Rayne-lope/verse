from verse.latency import LatencyEvent, LatencyTracker


def test_latency_tracker_summary_computes_stage_metrics():
    tracker = LatencyTracker("turn-1")
    tracker.t0 = 100.0
    tracker.set_metadata(
        audio_ms=1240,
        transcript_chars=42,
        provider={"stt": "groq", "llm": "deepseek", "tts": "edge-tts"},
    )
    tracker.events = [
        LatencyEvent("vad_speech_end", 100.100),
        LatencyEvent("stt_start", 100.120),
        LatencyEvent("stt_final", 100.970),
        LatencyEvent("local_intent_start", 100.971),
        LatencyEvent("local_intent_done", 100.972, {"matched": False}),
        LatencyEvent("llm_request_start", 101.000),
        LatencyEvent("llm_first_token", 101.620),
        LatencyEvent("tool_start", 101.700, {"name": "get_weather"}),
        LatencyEvent("tool_done", 101.900, {"name": "get_weather"}),
        LatencyEvent("llm_done", 102.700),
        LatencyEvent("tts_request_start", 102.720),
        LatencyEvent("tts_first_audio", 103.150),
        LatencyEvent("playback_start", 103.160),
        LatencyEvent("playback_done", 104.000),
        LatencyEvent("turn_done", 104.010),
    ]

    summary = tracker.summary()

    assert summary["turn_id"] == "turn-1"
    assert summary["audio_ms"] == 1240
    assert summary["transcript_chars"] == 42
    assert summary["provider"] == {"stt": "groq", "llm": "deepseek", "tts": "edge-tts"}
    assert summary["latency"]["vad_to_stt_start_ms"] == 20
    assert summary["latency"]["stt_ms"] == 850
    assert summary["latency"]["llm_first_token_ms"] == 620
    assert summary["latency"]["llm_total_ms"] == 1700
    assert summary["latency"]["tts_first_audio_ms"] == 430
    assert summary["latency"]["speech_end_to_first_audio_ms"] == 3050
    assert summary["latency"]["tools_ms"] == 200
    assert summary["tool_count"] == 1
    assert summary["cancelled"] is False
    assert summary["events"][0] == {"name": "vad_speech_end", "ms": 100, "data": {}}


def test_latency_tracker_summary_marks_cancelled_turns():
    tracker = LatencyTracker("turn-2")
    tracker.t0 = 10.0
    tracker.events = [
        LatencyEvent("barge_in_detected", 10.100),
        LatencyEvent("cancel_start", 10.110),
        LatencyEvent("cancel_done", 10.180),
    ]

    summary = tracker.summary()

    assert summary["cancelled"] is True
    assert summary["latency"]["cancellation_ms"] == 70
