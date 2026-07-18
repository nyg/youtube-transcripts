import { useState } from "react"

import { useSummaries } from "@/api/queries"
import { SummaryCard } from "@/components/SummaryCard"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface Props {
  channelId: number
}

export function SummaryList({ channelId }: Props) {
  const [scope, setScope] = useState<"channel" | "all">("channel")
  const { data: summaries, isLoading } = useSummaries(
    scope === "channel" ? channelId : undefined,
  )

  return (
    <div className="space-y-4">
      <Tabs value={scope} onValueChange={(v) => setScope(v as "channel" | "all")}>
        <TabsList>
          <TabsTrigger value="channel">This channel</TabsTrigger>
          <TabsTrigger value="all">All channels</TabsTrigger>
        </TabsList>
      </Tabs>

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
