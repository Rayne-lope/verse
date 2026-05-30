import { useBlink } from "../hooks/useBlink";

export function Eyes() {
  const isBlinking = useBlink();

  return (
    <div className="eyes" data-blinking={isBlinking || undefined}>
      <div className="eye" />
      <div className="eye" />
    </div>
  );
}
