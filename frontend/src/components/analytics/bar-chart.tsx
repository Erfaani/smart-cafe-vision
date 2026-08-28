export interface BarChartDatum {
  label: string;
  value: number;
  title?: string;
}

/**
 * A plain, hand-rolled bar chart -- flexbox and percentage heights, not a
 * charting library or SVG: there is no coordinate space to map here (unlike
 * the zone editor or the display's overlay, which place points in a real
 * camera's pixel space), just proportional bars, and this dashboard has no
 * other chart-library dependency to justify adding one for.
 *
 * `minBarWidth` keeps a long range (a year of daily bars) from squashing
 * into illegible slivers -- the container scrolls horizontally instead.
 */
export function BarChart({
  data,
  height = 140,
  minBarWidth = 18,
  formatValue,
}: {
  data: BarChartDatum[];
  height?: number;
  minBarWidth?: number;
  formatValue?: (value: number) => string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));

  if (data.length === 0) {
    return <p className="text-sm text-ink-muted">No data for this range.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <div
        className="flex items-end gap-1"
        style={{ height, minWidth: data.length * (minBarWidth + 4) }}
      >
        {data.map((d, i) => (
          <div key={i} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
            <div
              className="w-full rounded-t bg-accent/70"
              style={{ height: `${Math.max((d.value / max) * 100, d.value > 0 ? 2 : 0)}%` }}
              title={d.title ?? `${d.label}: ${formatValue ? formatValue(d.value) : d.value}`}
            />
            <span className="w-full truncate text-center text-[10px] text-ink-muted">{d.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
