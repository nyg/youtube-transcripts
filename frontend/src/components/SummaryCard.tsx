import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { useSummaryDetail } from "@/api/queries"
import type { Summary } from "@/api/types"
import { formatDateTime } from "@/lib/datetime"
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
  const detail = useSummaryDetail(summary.video_id, showTranscript)

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <a
            href={summary.url}
            target="_blank"
            rel="noreferrer"
            className="hover:underline"
          >
            {summary.title}
          </a>
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
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {summary.ai_response}
          </ReactMarkdown>
        </div>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3">
        <Button
          variant="ghost"
          size="sm"
          className="self-start"
          onClick={() => setShowTranscript((v) => !v)}
        >
          {showTranscript ? "Hide transcript" : "Show transcript"}
        </Button>
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
