import { useState } from "react"

import { EstimateDialog } from "@/components/EstimateDialog"
import { JobProgress } from "@/components/JobProgress"
import { VideoTable } from "@/components/VideoTable"

interface Props {
  channelId: number
}

export function ProcessTab({ channelId }: Props) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [estimateOpen, setEstimateOpen] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)

  return (
    <div className="space-y-6">
      {jobId && <JobProgress jobId={jobId} onDismiss={() => setJobId(null)} />}
      <VideoTable
        channelId={channelId}
        selected={selected}
        onSelectedChange={setSelected}
        onEstimate={() => setEstimateOpen(true)}
      />
      <EstimateDialog
        open={estimateOpen}
        onOpenChange={setEstimateOpen}
        channelId={channelId}
        videoIds={[...selected]}
        onJobCreated={(id) => {
          setEstimateOpen(false)
          setSelected(new Set())
          setJobId(id)
        }}
      />
    </div>
  )
}
