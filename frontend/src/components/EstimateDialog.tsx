import { Loader2 } from "lucide-react"
import { useEffect } from "react"
import { toast } from "sonner"

import { ApiError } from "@/api/client"
import { useCreateEstimate, useCreateJob } from "@/api/queries"
import { TRANSCRIPT_SOURCES } from "@/lib/transcript"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  channelId: number
  videoIds: string[]
  onJobCreated: (jobId: string) => void
}

const fmtCost = (cost: number | null | undefined) =>
  cost != null ? `$${cost.toFixed(4)}` : "n/a"

export function EstimateDialog({
  open,
  onOpenChange,
  channelId,
  videoIds,
  onJobCreated,
}: Props) {
  const estimate = useCreateEstimate()
  const createJob = useCreateJob()

  const videoKey = videoIds.join(",")

  // (Re-)estimate whenever the dialog opens or the selection changes. The prompt
  // is the channel's chosen prompt, resolved server-side — not selectable here.
  useEffect(() => {
    if (!open || videoIds.length === 0) return
    estimate.mutate(
      { channel_id: channelId, video_ids: videoIds },
      { onError: (error) => toast.error(error.message) },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, videoKey, channelId])

  const result = estimate.data
  const okItems = result?.items.filter((item) => item.status === "ok") ?? []
  const assumedTokens =
    okItems.find((item) => item.estimated_output_tokens != null)?.estimated_output_tokens ??
    null

  const approve = () => {
    if (!result) return
    createJob.mutate(result.estimate_id, {
      onSuccess: ({ job_id }) => onJobCreated(job_id),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 410) {
          toast.warning("Estimate expired. Running it again.")
          estimate.mutate({ channel_id: channelId, video_ids: videoIds })
        } else {
          toast.error(error.message)
        }
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Cost estimate</DialogTitle>
          <DialogDescription>
            Estimates are free. Nothing is sent to Claude until you approve.
          </DialogDescription>
        </DialogHeader>

        {result && (
          <p className="text-muted-foreground text-xs">
            {result.model}
            {result.effort && `, ${result.effort} effort`}, prompt “{result.prompt_name}”
            {assumedTokens != null &&
              `, ~${assumedTokens.toLocaleString()} output tokens per video`}
            .
          </p>
        )}

        {estimate.isPending && (
          <div className="text-muted-foreground flex items-center justify-center gap-2 py-10 text-sm">
            <Loader2 className="animate-spin" />
            Fetching transcripts and counting tokens…
          </div>
        )}

        {!estimate.isPending && result && (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Video</TableHead>
                  <TableHead className="w-32 text-right">Input tokens</TableHead>
                  <TableHead className="w-24 text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.items.map((item) => (
                  <TableRow key={item.video_id}>
                    <TableCell className="whitespace-normal">
                      <span className={item.status === "ok" ? "" : "line-through opacity-60"}>
                        {item.title}
                      </span>
                      {item.status === "no_transcript" && (
                        <p className="text-destructive mt-0.5 text-xs">
                          Skipped. {item.detail}
                        </p>
                      )}
                      {item.transcript_source && (
                        <p
                          className="text-muted-foreground mt-0.5 text-xs"
                          title={TRANSCRIPT_SOURCES[item.transcript_source].hint}
                        >
                          {TRANSCRIPT_SOURCES[item.transcript_source].label}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {item.input_tokens?.toLocaleString() ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {item.status === "ok" ? fmtCost(item.cost_usd) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell className="font-medium">
                    Total ({okItems.length} of {result.items.length} videos)
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {result.total_input_tokens.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {fmtCost(result.total_cost_usd)}
                  </TableCell>
                </TableRow>
              </TableFooter>
            </Table>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={approve}
            disabled={
              estimate.isPending ||
              createJob.isPending ||
              !result ||
              okItems.length === 0
            }
          >
            {createJob.isPending && <Loader2 className="animate-spin" />}
            {okItems.length > 0
              ? `Summarize ${okItems.length} · ${fmtCost(result?.total_cost_usd)}`
              : "Summarize"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
