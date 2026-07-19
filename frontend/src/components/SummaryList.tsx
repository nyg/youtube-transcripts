import { useSummaries } from "@/api/queries"
import { SummaryCard } from "@/components/SummaryCard"
import { Skeleton } from "@/components/ui/skeleton"

interface Props {
  channelId: number
}

export function SummaryList({ channelId }: Props) {
  const { data: summaries, isLoading } = useSummaries(channelId)

  return (
    <div className="space-y-4">
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      )}

      {summaries && summaries.length === 0 && (
        <p className="text-muted-foreground py-16 text-center">
          No summaries yet — process some videos first.
        </p>
      )}

      {(summaries ?? []).map((summary) => (
        <SummaryCard key={summary.video_id} summary={summary} />
      ))}
    </div>
  )
}
