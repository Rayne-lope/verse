import React, { createContext, useContext, useCallback, useEffect, useRef, useState } from "react";
import type {
  ApiKeyStatus,
  ConnectionStatus,
  IncomingMessage,
  MicStatusMessage,
  OutgoingMessage,
  VerseConfig,
  VerseState,
} from "../types/ws";

const DEFAULT_URL = "ws://localhost:8765";
const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;

export interface WebSocketContextValue {
  connectionStatus: ConnectionStatus;
  lastState: VerseState | null;
  audioLevel: number;
  transcript: string;
  userPartialTranscript: string;
  assistantText: string;
  micStatus: MicStatusMessage | null;
  config: VerseConfig | null;
  apiKeys: ApiKeyStatus | null;
  onboardingNeeded: boolean;
  send: (message: OutgoingMessage) => void;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

export function WebSocketProvider({
  children,
  url = DEFAULT_URL,
}: {
  children: React.ReactNode;
  url?: string;
}) {
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const [lastState, setLastState] = useState<VerseState | null>(null);
  const [audioLevel, setAudioLevel] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [userPartialTranscript, setUserPartialTranscript] = useState("");
  const [assistantText, setAssistantText] = useState("");
  const [micStatus, setMicStatus] = useState<MicStatusMessage | null>(null);
  const [config, setConfig] = useState<VerseConfig | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKeyStatus | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUnmountRef = useRef(false);

  const handleMessage = useCallback((raw: string) => {
    let message: IncomingMessage;
    try {
      message = JSON.parse(raw) as IncomingMessage;
    } catch {
      return;
    }

    if (import.meta.env.DEV) {
      switch (message.type) {
        case "state_change":
          console.debug("[Verse WS] state", message.state);
          break;
        case "pipeline_event":
          console.debug("[Verse WS] pipeline", message.stage, message.event, message);
          break;
        case "vad_update":
          console.debug("[Verse WS] vad", message.state, message.probability);
          break;
        default:
          break;
      }
    }

    switch (message.type) {
      case "state_change":
        setLastState(message.state);
        if (message.state === "listening") {
          setTranscript("");
          setUserPartialTranscript("");
          setAssistantText("");
        }
        break;
      case "audio_level":
        setAudioLevel(message.level);
        break;
      case "mic_status":
        setMicStatus(message);
        break;
      case "transcript":
        setTranscript(message.text);
        break;
      case "user_partial_transcript":
        setUserPartialTranscript(message.text);
        break;
      case "user_final_transcript":
        setTranscript(message.text);
        setUserPartialTranscript("");
        break;
      case "assistant_text":
        setAssistantText(message.text);
        break;
      case "error":
        setLastState("error");
        break;
      case "config_data":
        setConfig(message.config);
        setApiKeys(message.api_keys);
        break;
      case "config_updated":
      case "api_key_set":
        break;
      case "pipeline_event":
      case "vad_update":
        break;
      default:
        break;
    }
  }, []);

  useEffect(() => {
    closedByUnmountRef.current = false;

    const connect = () => {
      setConnectionStatus("connecting");
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        backoffRef.current = INITIAL_BACKOFF_MS;
        setConnectionStatus("open");
      };

      socket.onmessage = (event) => {
        handleMessage(event.data as string);
      };

      socket.onclose = () => {
        socketRef.current = null;
        if (closedByUnmountRef.current) {
          setConnectionStatus("closed");
          return;
        }
        setConnectionStatus("connecting");
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS);
        reconnectTimerRef.current = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      closedByUnmountRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [url, handleMessage]);

  const send = useCallback((message: OutgoingMessage) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }, []);

  const dismissed = typeof localStorage !== "undefined"
    ? localStorage.getItem("verse.onboarded") === "dismissed"
    : false;
  const onboardingNeeded = !dismissed && apiKeys !== null && (!apiKeys.groq || !apiKeys.deepseek);

  const value = React.useMemo(
    () => ({
      connectionStatus,
      lastState,
      audioLevel,
      transcript,
      userPartialTranscript,
      assistantText,
      micStatus,
      config,
      apiKeys,
      onboardingNeeded,
      send,
    }),
    [connectionStatus, lastState, audioLevel, transcript, userPartialTranscript, assistantText, micStatus, config, apiKeys, onboardingNeeded, send]
  );

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket(): WebSocketContextValue {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error("useWebSocket must be used within a WebSocketProvider");
  }
  return context;
}
