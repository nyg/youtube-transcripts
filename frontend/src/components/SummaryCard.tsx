import { useEffect, useState } from "react"
import { Trash2 } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"

import { useDeleteSummary, useSummaryDetail } from "@/api/queries"
import type { Summary } from "@/api/types"
import { formatDateTime } from "@/lib/datetime"
import { stanceClass } from "@/lib/stance"
import { TRANSCRIPT_SOURCES } from "@/lib/transcript"
import { youtubeAt } from "@/lib/youtube"
import { SummaryStats } from "@/components/SummaryStats"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"

interface Props {
  summary: Summary
}

export function SummaryCard({ summary }: Props) {
  const [showTranscript, setShowTranscript] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const detail = useSummaryDetail(summary.video_id, showTranscript)
  const deleteSummary = useDeleteSummary()
  // Deleting drops the summary *and* its transcript for good, so the trash icon
  // arms first and only deletes on a second click.
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    if (!confirming) return
    const timer = setTimeout(() => setConfirming(false), 4000)
    return () => clearTimeout(timer)
  }, [confirming])

  const remove = () => {
    if (!confirming) {
      setConfirming(true)
      return
    }
    deleteSummary.mutate(summary.video_id, {
      onSuccess: () => toast.success(`Deleted “${summary.title}”`),
      onError: (error) => toast.error(error.message),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-start justify-between gap-2">
          <a
            href={summary.url}
            target="_blank"
            rel="noreferrer"
            className="hover:underline"
          >
            {summary.title}
          </a>
          <Button
            variant={confirming ? "destructive" : "ghost"}
            size={confirming ? "sm" : "icon"}
            className="shrink-0"
            aria-label={
              confirming
                ? `Confirm deleting ${summary.title}`
                : `Delete ${summary.title}`
            }
            title={
              confirming
                ? "Click again to delete the summary and its transcript"
                : "Delete summary"
            }
            disabled={deleteSummary.isPending}
            onClick={remove}
            onBlur={() => setConfirming(false)}
          >
            <Trash2 className={confirming ? undefined : "text-destructive"} />
            {confirming && "Delete?"}
          </Button>
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          <span>{formatDateTime(summary.published_at)}</span>
          <Badge variant="outline">{summary.model}</Badge>
          <Badge variant="outline">{summary.prompt_name}</Badge>
          {summary.cost_usd != null && (
            <Badge variant="outline">${summary.cost_usd.toFixed(4)}</Badge>
          )}
          {summary.tokens_input != null && summary.tokens_output != null && (
            <Badge variant="outline">
              {summary.tokens_input.toLocaleString()} in /{" "}
              {summary.tokens_output.toLocaleString()} out
            </Badge>
          )}
          {summary.transcript_source && (
            <Badge variant="outline" title={TRANSCRIPT_SOURCES[summary.transcript_source].hint}>
              {TRANSCRIPT_SOURCES[summary.transcript_source].label}
            </Badge>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {summary.mentions.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {summary.mentions.map((mention, index) => {
              const link = youtubeAt(summary.url, mention.timestamp_seconds)
              const chip = (
                <Badge variant="outline" className={stanceClass(mention.stance)}>
                  {mention.entity} · {mention.stance}
                </Badge>
              )
              return link ? (
                <a
                  key={`${mention.entity_key}-${index}`}
                  href={link}
                  target="_blank"
                  rel="noreferrer"
                  title={mention.rationale ?? undefined}
                >
                  {chip}
                </a>
              ) : (
                <span key={`${mention.entity_key}-${index}`} title={mention.rationale ?? undefined}>
                  {chip}
                </span>
              )
            })}
          </div>
        )}
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {summary.ai_response}
          </ReactMarkdown>
        </div>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3">
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => setShowTranscript((v) => !v)}>
            {showTranscript ? "Hide transcript" : "Show transcript"}
          </Button>
          {summary.max_output_tokens != null && (
            <Button variant="ghost" size="sm" onClick={() => setShowStats((v) => !v)}>
              {showStats ? "Hide stats" : "Show stats"}
            </Button>
          )}
        </div>
        {showStats && <SummaryStats summary={summary} />}
        {showTranscript && (
          <ScrollArea className="bg-muted h-56 rounded-md p-3">
            <p className="text-muted-foreground text-xs whitespace-pre-wrap">
              {detail.isLoading ? "Loading transcript…" : detail.data?.transcript}
            </p>
          </ScrollArea>
        )}
      </CardFooter>
    </Card>
  )
}
