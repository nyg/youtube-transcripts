import { useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { useEffect, useRef } from "react"
import { toast } from "sonner"

import { useJob } from "@/api/queries"
import type { JobItem } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

interface Props {
  jobId: string
  onDismiss: () => void
}

function StatusBadge({ item }: { item: JobItem }) {
  switch (item.status) {
    case "queued":
      return <Badge variant="secondary">Queued</Badge>
    case "processing":
      return (
        <Badge>
          <Loader2 className="animate-spin" />
          Summarizing
        </Badge>
      )
    case "done":
      return (
        <Badge variant="outline" className="border-green-600 text-green-600">
          Done{item.cost_usd != null && ` · $${item.cost_usd.toFixed(4)}`}
        </Badge>
      )
    case "failed":
      return <Badge variant="destructive">Failed</Badge>
  }
}

export function JobProgress({ jobId, onDismiss }: Props) {
  const { data: job } = useJob(jobId)
  const queryClient = useQueryClient()
  const notified = useRef(false)

  useEffect(() => {
    if (job?.status === "done" && !notified.current) {
      notified.current = true
      const failed = job.items.filter((item) => item.status === "failed").length
      const done = job.items.length - failed
      const message = `Summarized ${done} video${done === 1 ? "" : "s"} for $${job.total_cost_usd.toFixed(4)}`
      if (failed > 0) toast.warning(`${message}, ${failed} failed`)
      else toast.success(message)
      queryClient.invalidateQueries({ queryKey: ["videos"] })
      queryClient.invalidateQueries({ queryKey: ["summaries"] })
      queryClient.invalidateQueries({ queryKey: ["entities"] })
      queryClient.invalidateQueries({ queryKey: ["mentions"] })
    }
  }, [job, queryClient])

  if (!job) return null

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>
          {job.status === "running" ? "Summarizing…" : "Summaries ready"}
        </CardTitle>
        {job.status === "done" && (
          <Button variant="outline" size="sm" onClick={onDismiss}>
            Dismiss
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {job.items.map((item) => (
            <li key={item.video_id} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate text-sm">{item.title}</span>
              <div className="flex shrink-0 items-center gap-2">
                {item.status === "failed" && item.error && (
                  <span className="text-destructive max-w-64 truncate text-xs" title={item.error}>
                    {item.error}
                  </span>
                )}
                <StatusBadge item={item} />
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
