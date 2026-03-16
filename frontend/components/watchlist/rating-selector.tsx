/**
 * 1-10 rating selector for watchlist items.
 */

interface RatingSelectorProps {
  value: number | null;
  onChange: (rating: number) => void;
}

export function RatingSelector({ value, onChange }: RatingSelectorProps) {
  return (
    <div className="flex items-center gap-1">
      <span className="mr-1 text-xs text-muted-foreground">Your rating:</span>
      {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
        <button
          key={n}
          onClick={() => onChange(n)}
          className={`h-5 w-5 rounded text-xs font-medium transition ${
            value && n <= value
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
          }`}
        >
          {n}
        </button>
      ))}
    </div>
  );
}
