// A plain headline figure: a label, a big value and a line under it (for figures that are not an indicator).
export default function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card tile htile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="small muted">{note}</div> : null}
    </div>
  );
}
