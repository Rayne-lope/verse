export type VerseState =
  | "idle"
  | "listening"
  | "endpointing"
  | "transcribing"
  | "thinking"
  | "acting"
  | "preparing_audio"
  | "speaking"
  | "interrupted"
  | "error";

export interface StateChangeMessage {
  type: "state_change";
  state: VerseState;
  turn_id?: number | string | null;
}

export interface AudioLevelMessage {
  type: "audio_level";
  level: number;
  turn_id?: number | string | null;
}

export interface MicStatusMessage {
  type: "mic_status";
  active: boolean;
  mode: "ambient" | "recording" | "off" | string;
}

export interface TranscriptMessage {
  type: "transcript";
  text: string;
  partial: boolean;
  turn_id?: number | string | null;
}

export interface UserPartialTranscriptMessage {
  type: "user_partial_transcript";
  text: string;
  stability: number | null;
  turn_id?: number | string | null;
}

export interface UserFinalTranscriptMessage {
  type: "user_final_transcript";
  text: string;
  turn_id?: number | string | null;
}

export interface AssistantTextMessage {
  type: "assistant_text";
  text: string;
  turn_id?: number | string | null;
}

export interface ToolExecutedMessage {
  type: "tool_executed";
  name: string;
  result: unknown;
  turn_id?: number | string | null;
}

export interface ErrorMessage {
  type: "error";
  message: string;
  recoverable: boolean;
  turn_id?: number | string | null;
}

export interface PipelineEventMessage {
  type: "pipeline_event";
  stage: string;
  event: string;
  turn_id?: number | string | null;
  [key: string]: unknown;
}

export interface VADUpdateMessage {
  type: "vad_update";
  state: string;
  probability: number;
  turn_id?: number | string | null;
}

export interface VerseConfig {
  tts: { provider: string; voice_id: string; speed: number; model: string; base_url: string };
  stt: { language: string; partial_mode?: string };
  llm: { provider: string; model: string; base_url: string; temperature: number; max_history: number };
  hotkey: { trigger: string };
  always_on: {
    enabled: boolean;
    keyword: string;
    keyword_path: string;
    model_path: string;
    sensitivity: number;
    device: string;
  };
  memory: { enabled: boolean; max_facts: number };
  voice?: { engine: string; low_latency: boolean };
}

export interface ApiKeyStatus {
  groq: boolean;
  deepseek: boolean;
  gemini: boolean;
  brave: boolean;
  spotify: boolean;
  picovoice: boolean;
}

export interface ConfigDataMessage {
  type: "config_data";
  config: VerseConfig;
  api_keys: ApiKeyStatus;
}

export interface ConfigUpdatedMessage {
  type: "config_updated";
  success: boolean;
  error?: string;
}

export interface ApiKeySetMessage {
  type: "api_key_set";
  key_name: string;
  success: boolean;
}

export interface NowPlayingMessage {
  type: "now_playing";
  playing: boolean;
  player: string;
  track: string;
  artist: string;
  artwork_url?: string | null;
}

export type IncomingMessage =
  | StateChangeMessage
  | AudioLevelMessage
  | MicStatusMessage
  | TranscriptMessage
  | UserPartialTranscriptMessage
  | UserFinalTranscriptMessage
  | AssistantTextMessage
  | ToolExecutedMessage
  | ErrorMessage
  | PipelineEventMessage
  | VADUpdateMessage
  | ConfigDataMessage
  | ConfigUpdatedMessage
  | ApiKeySetMessage
  | NowPlayingMessage;


export type ManualTriggerAction =
  | "start_listening"
  | "stop_listening"
  | "toggle_conversation"
  | "deactivate_conversation";

export interface ManualTriggerMessage {
  type: "manual_trigger";
  action: ManualTriggerAction;
}

export interface InterruptMessage {
  type: "interrupt";
}

export interface GetConfigMessage {
  type: "get_config";
}

export interface UpdateConfigMessage {
  type: "update_config";
  section: string;
  key: string;
  value: string | number | boolean;
}

export interface SetApiKeyMessage {
  type: "set_api_key";
  key_name: string;
  value: string;
}

export type OutgoingMessage =
  | ManualTriggerMessage
  | InterruptMessage
  | GetConfigMessage
  | UpdateConfigMessage
  | SetApiKeyMessage;

export type ConnectionStatus = "connecting" | "open" | "closed";
