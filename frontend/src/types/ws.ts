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

export type IncomingMessage =
  | StateChangeMessage
  | AudioLevelMessage
  | TranscriptMessage
  | AssistantTextMessage
  | ToolExecutedMessage
  | ErrorMessage;

export type ManualTriggerAction = "start_listening" | "stop_listening";

export interface ManualTriggerMessage {
  type: "manual_trigger";
  action: ManualTriggerAction;
}

export interface InterruptMessage {
  type: "interrupt";
}

export type OutgoingMessage = ManualTriggerMessage | InterruptMessage;

export type ConnectionStatus = "connecting" | "open" | "closed";
