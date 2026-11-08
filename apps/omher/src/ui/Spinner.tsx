export function Spinner({ size = 12, label = "Working" }: { size?: number; label?: string }) {
  return <span className="ui-spin" role="status" aria-label={label} style={{ width: size, height: size }} />;
}
