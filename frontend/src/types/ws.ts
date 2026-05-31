export type VerseState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export interface StateChangeMessage {
  type: "state_change";
  state: VerseState;
}

export interface AudioLevelMessage {
  type: "audio_level";
  level: number;
}

export interface TranscriptMessage {
  type: "transcript";
  text: string;
  partial: boolean;
}

export interface AssistantTextMessage {
  type: "assistant_text";
  text: string;
}

export interface ToolExecutedMessage {
  type: "tool_executed";
  name: string;
  result: unknown;
}

export interface ErrorMessage {
  type: "error";
  message: string;
  recoverable: boolean;
}

export interface PipelineEventMessage {
  type: "pipeline_event";
  stage: string;
  event: string;
  [key: string]: unknown;
}

export interface VADUpdateMessage {
  type: "vad_update";
  state: string;
  probability: number;
}

export interface VerseConfig {
  tts: { provider: string; voice_id: string; speed: number };
  stt: { language: string };
  llm: { provider: string; model: string; temperature: number; max_history: number };
  hotkey: { trigger: string };
  memory: { enabled: boolean; max_facts: number };
}

export interface ApiKeyStatus {
  groq: boolean;
  deepseek: boolean;
  brave: boolean;
  spotify: boolean;
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

export type IncomingMessage =
  | StateChangeMessage
  | AudioLevelMessage
  | TranscriptMessage
  | AssistantTextMessage
  | ToolExecutedMessage
  | ErrorMessage
  | PipelineEventMessage
  | VADUpdateMessage
  | ConfigDataMessage
  | ConfigUpdatedMessage
  | ApiKeySetMessage;

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
