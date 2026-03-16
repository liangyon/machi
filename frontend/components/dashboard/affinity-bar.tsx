/**
 * Horizontal bar showing genre/theme affinity on the dashboard.
 */

interface AffinityBarProps {
  label: string;
  value: number;
  max: number;
  detail: string;
}

export function AffinityBar({ label, value, max, detail }: AffinityBarProps) {
  const pct = (value / max) * 100;
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{detail}</span>
      </div>
      <div className="mt-1 h-2 w-full rounded-full bg-muted">
        <div
          className="h-2 rounded-full bg-violet-500 transition-all dark:bg-violet-400"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
