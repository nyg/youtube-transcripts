import { useMentions } from "@/api/queries"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { formatPublished } from "@/lib/datetime"
import { stanceClass } from "@/lib/stance"
import { youtubeAt } from "@/lib/youtube"

export function MentionTimeline({
  channelId,
  entity,
  since,
}: {
  channelId: number | undefined
  entity: string
  since: string | undefined
}) {
  const { data: mentions, isLoading } = useMentions(channelId, entity, since)

  if (isLoading) return <Skeleton className="h-16 w-full" />
  if (!mentions || mentions.length === 0) {
    return <p className="text-muted-foreground text-sm">No mentions in this period.</p>
  }

  return (
    <ol className="space-y-3">
      {mentions.map((mention, index) => {
        const link = youtubeAt(mention.url, mention.timestamp_seconds)
        return (
          <li key={`${mention.video_id}-${index}`} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className={stanceClass(mention.stance)}>
                {mention.stance}
              </Badge>
              <span className="text-muted-foreground">
                {formatPublished(mention.published_at)}
              </span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">{mention.confidence} confidence</span>
              {link && (
                <a
                  href={link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-muted-foreground hover:text-foreground underline underline-offset-2"
                >
                  {mention.title ?? "Watch"}
                  {mention.timestamp_seconds !== null && " ↗"}
                </a>
              )}
            </div>
            {mention.rationale && <p className="mt-1">{mention.rationale}</p>}
            {mention.quote && (
              <blockquote className="text-muted-foreground mt-1 border-l-2 pl-3 italic">
                “{mention.quote}”
              </blockquote>
            )}
          </li>
        )
      })}
    </ol>
  )
}
