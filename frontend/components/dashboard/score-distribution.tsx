/**
 * Horizontal bar chart showing the user's score distribution.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ScoreDistributionProps {
  distribution: Record<string, number>;
}

export function ScoreDistribution({ distribution }: ScoreDistributionProps) {
  const entries = Object.entries(distribution)
    .map(([score, count]) => ({ score: parseInt(score), count }))
    .sort((a, b) => a.score - b.score);

  const maxCount = Math.max(...entries.map((s) => s.count), 1);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Score Distribution</CardTitle>
        <CardDescription>
          How you rate anime — are you generous or harsh?
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map(({ score, count }) => (
          <div key={score} className="flex items-center gap-3">
            <span className="w-6 text-right text-xs font-medium text-muted-foreground">
              {score}
            </span>
            <div className="flex-1">
              <div
                className="h-5 rounded bg-primary/80 transition-all"
                style={{
                  width: `${(count / maxCount) * 100}%`,
                  minWidth: count > 0 ? "4px" : "0",
                }}
              />
            </div>
            <span className="w-8 text-xs text-muted-foreground">{count}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
