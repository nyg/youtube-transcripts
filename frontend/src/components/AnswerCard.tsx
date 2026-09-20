import { Trash2 } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"

import { useDeleteQuestion } from "@/api/queries"
import type { Question, Source } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { formatDateTime } from "@/lib/datetime"
import { youtubeAt } from "@/lib/youtube"

function sourceLink(source: Source): string {
  return youtubeAt(source.url, source.start_seconds) ?? source.url
}

function withCitationLinks(answer: string, sources: Source[]): string {
  const byNumber = new Map(sources.map((source) => [source.number, source]))
  return answer.replace(/\[(\d+)\]/g, (match, digits) => {
    const source = byNumber.get(Number(digits))
    return source ? `[[${digits}]](${sourceLink(source)})` : match
  })
}

export function AnswerCard({ question }: { question: Question }) {
  const deleteQuestion = useDeleteQuestion()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-start justify-between gap-2">
          <span>{question.question}</span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Delete question"
            disabled={deleteQuestion.isPending}
            onClick={() =>
              deleteQuestion.mutate(question.id, {
                onError: (error) => toast.error(error.message),
              })
            }
          >
            <Trash2 className="text-destructive" />
          </Button>
        </CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          <span>{formatDateTime(question.created_at)}</span>
          <Badge variant="outline">{question.model}</Badge>
          {question.cost_usd != null && (
            <Badge variant="outline">${question.cost_usd.toFixed(4)}</Badge>
          )}
          <Badge variant="outline">{question.sources.length} sources</Badge>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {withCitationLinks(question.answer, question.sources)}
          </ReactMarkdown>
        </div>
        <details className="text-sm">
          <summary className="text-muted-foreground cursor-pointer">Sources</summary>
          <ol className="mt-2 space-y-1">
            {question.sources.map((source) => (
              <li key={source.number} className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground tabular-nums">[{source.number}]</span>
                <Badge variant="secondary">{source.kind}</Badge>
                <a
                  href={sourceLink(source)}
                  target="_blank"
                  rel="noreferrer"
                  className="hover:underline"
                >
                  {source.title}
                </a>
              </li>
            ))}
          </ol>
        </details>
      </CardContent>
    </Card>
  )
}
