import { useWebSocket } from "./useWebSocket";

export function useAudioLevel(): number {
  const { audioLevel } = useWebSocket();
  return audioLevel;
}
