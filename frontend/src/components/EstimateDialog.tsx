import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ApiError } from "@/api/client"
import { useCreateEstimate, useCreateJob, useMeta } from "@/api/queries"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
  const { data: meta } = useMeta()
  const [promptName, setPromptName] = useState<string | null>(null)
  const estimate = useCreateEstimate()
  const createJob = useCreateJob()

  const effectivePrompt = promptName ?? meta?.active_prompt
  const videoKey = videoIds.join(",")

  // (Re-)estimate whenever the dialog opens or the prompt changes — the
  // prompt is part of the input token count.
  useEffect(() => {
    if (!open || videoIds.length === 0 || !effectivePrompt) return
    estimate.mutate(
      { channel_id: channelId, video_ids: videoIds, prompt_name: effectivePrompt },
      { onError: (error) => toast.error(error.message) },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, videoKey, effectivePrompt, channelId])

  const result = estimate.data
  const okItems = result?.items.filter((item) => item.status === "ok") ?? []

  const approve = () => {
    if (!result) return
    createJob.mutate(result.estimate_id, {
      onSuccess: ({ job_id }) => onJobCreated(job_id),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 410) {
          toast.warning("Estimate expired — re-running it now.")
          estimate.mutate({
            channel_id: channelId,
            video_ids: videoIds,
            prompt_name: effectivePrompt,
          })
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
            Counting tokens is free — nothing is sent to Claude until you
            approve.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-end gap-3">
          <div className="space-y-1.5">
            <Label>Prompt</Label>
            <Select
              value={effectivePrompt}
              onValueChange={setPromptName}
              disabled={estimate.isPending}
            >
              <SelectTrigger className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(meta?.prompts ?? []).map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {meta && (
            <p className="text-muted-foreground pb-2 text-xs">
              Model {meta.model}, assuming ~
              {meta.estimated_output_tokens.toLocaleString()} output tokens per
              video.
            </p>
          )}
        </div>

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
                  <TableHead className="w-24 text-right">Est. cost</TableHead>
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
                          No transcript — skipped. {item.detail}
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
            Approve — send {okItems.length > 0 ? okItems.length : ""} to Claude (
            {fmtCost(result?.total_cost_usd)})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
