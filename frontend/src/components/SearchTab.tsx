import { useEffect, useMemo, useState } from "react"

import { useSearch } from "@/api/queries"
import type { SearchHit } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { formatPublished } from "@/lib/datetime"
import { youtubeAt } from "@/lib/youtube"

const HIGHLIGHT_START = ""
const HIGHLIGHT_END = ""

function Snippet({ text }: { text: string }) {
  const parts = text.split(HIGHLIGHT_START).flatMap((chunk, index) => {
    if (index === 0) return [{ marked: false, text: chunk }]
    const [marked, rest = ""] = chunk.split(HIGHLIGHT_END)
    return [
      { marked: true, text: marked },
      { marked: false, text: rest },
    ]
  })
  return (
    <p className="text-sm">
      {parts.map((part, index) =>
        part.marked ? (
          <mark key={index} className="bg-amber-200 dark:bg-amber-500/40">
            {part.text}
          </mark>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </p>
  )
}

function stamp(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  const mm = String(minutes).padStart(2, "0")
  const ss = String(secs).padStart(2, "0")
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

export function SearchTab({ channelId }: { channelId: number }) {
  const [text, setText] = useState("")
  const [debounced, setDebounced] = useState("")
  const [allChannels, setAllChannels] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(text), 300)
    return () => clearTimeout(timer)
  }, [text])

  const scope = allChannels ? undefined : channelId
  const { data: hits, isFetching } = useSearch(debounced, scope)

  const grouped = useMemo(() => {
    const byVideo = new Map<string, SearchHit[]>()
    for (const hit of hits ?? []) {
      const existing = byVideo.get(hit.video_id)
      if (existing) existing.push(hit)
      else byVideo.set(hit.video_id, [hit])
    }
    return [...byVideo.values()]
  }, [hits])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Search transcripts and summaries…"
          className="max-w-96 flex-1"
        />
        <div className="flex items-center gap-2">
          <Checkbox
            id="search-all-channels"
            checked={allChannels}
            onCheckedChange={(checked) => setAllChannels(checked === true)}
          />
          <Label htmlFor="search-all-channels" className="font-normal">
            All channels
          </Label>
        </div>
      </div>

      {debounced.trim().length < 2 && (
        <p className="text-muted-foreground py-16 text-center">
          Type at least 2 characters. Each hit links to its moment in the video.
        </p>
      )}

      {debounced.trim().length >= 2 && isFetching && !hits && (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {debounced.trim().length >= 2 && hits && hits.length === 0 && (
        <p className="text-muted-foreground py-16 text-center">
          Nothing found for “{debounced.trim()}”.
        </p>
      )}

      <ul className="space-y-4">
        {grouped.map((videoHits) => {
          const first = videoHits[0]
          return (
            <li key={first.video_id} className="rounded-md border p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <a
                  href={first.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium hover:underline"
                >
                  {first.title}
                </a>
                <span className="text-muted-foreground text-sm">
                  {formatPublished(first.published_at)}
                </span>
                <Badge variant="outline">{videoHits.length} hit{videoHits.length > 1 && "s"}</Badge>
              </div>
              <ul className="space-y-2">
                {videoHits.map((hit, index) => {
                  const link = youtubeAt(hit.url, hit.start_seconds)
                  return (
                    <li key={`${hit.video_id}-${index}`} className="flex gap-2">
                      {hit.kind === "summary" ? (
                        <Badge variant="secondary" className="h-5 shrink-0">
                          summary
                        </Badge>
                      ) : (
                        <a
                          href={link ?? hit.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-muted-foreground hover:text-foreground h-5 shrink-0 text-sm tabular-nums underline underline-offset-2"
                        >
                          {hit.start_seconds === null ? "▶" : stamp(hit.start_seconds)}
                        </a>
                      )}
                      <Snippet text={hit.snippet} />
                    </li>
                  )
                })}
              </ul>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
