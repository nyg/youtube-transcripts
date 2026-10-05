import { RefreshCw } from "lucide-react"

import { useVideos } from "@/api/queries"
import { formatPublished } from "@/lib/datetime"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

interface Props {
  channelId: number
  selected: ReadonlySet<string>
  onSelectedChange: (selected: ReadonlySet<string>) => void
  onEstimate: () => void
}

export function VideoTable({ channelId, selected, onSelectedChange, onEstimate }: Props) {
  const { data, isLoading, isError, error, refetch, isRefetching } =
    useVideos(channelId)

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load videos</AlertTitle>
        <AlertDescription>
          {error.message}
          <Button variant="outline" size="sm" className="mt-2" onClick={() => refetch()}>
            Retry
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  const videos = data?.videos ?? []
  const newVideos = videos.filter((v) => !v.processed)
  const allNewSelected =
    newVideos.length > 0 && newVideos.every((v) => selected.has(v.video_id))

  const toggle = (videoId: string, checked: boolean) => {
    const next = new Set(selected)
    if (checked) next.add(videoId)
    else next.delete(videoId)
    onSelectedChange(next)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <p className="text-muted-foreground mr-auto text-sm">
          {videos.length} videos: {newVideos.length} new,{" "}
          {videos.length - newVideos.length} summarized. Select a summarized video to
          redo it.
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isRefetching}
        >
          <RefreshCw className={isRefetching ? "animate-spin" : ""} />
          Refresh
        </Button>
        <Button onClick={onEstimate} disabled={selected.size === 0}>
          Estimate cost ({selected.size})
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  aria-label="Select all new videos"
                  checked={allNewSelected}
                  disabled={newVideos.length === 0}
                  onCheckedChange={(checked) =>
                    onSelectedChange(
                      checked ? new Set(newVideos.map((v) => v.video_id)) : new Set(),
                    )
                  }
                />
              </TableHead>
              <TableHead className="w-36">Published</TableHead>
              <TableHead>Title</TableHead>
              <TableHead className="w-28">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {videos.map((video) => (
              <TableRow key={video.video_id}>
                <TableCell>
                  <Checkbox
                    aria-label={`Select ${video.title}`}
                    checked={selected.has(video.video_id)}
                    onCheckedChange={(checked) =>
                      toggle(video.video_id, checked === true)
                    }
                  />
                </TableCell>
                <TableCell className="text-muted-foreground whitespace-nowrap">
                  {formatPublished(video.published_at, video.date_approximate)}
                </TableCell>
                <TableCell className="whitespace-normal">
                  <a
                    href={video.url}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    {video.title}
                  </a>
                </TableCell>
                <TableCell>
                  {!video.processed ? (
                    <Badge>New</Badge>
                  ) : selected.has(video.video_id) ? (
                    <Badge variant="outline">Redo</Badge>
                  ) : (
                    <Badge variant="secondary">Summarized</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {videos.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground h-24 text-center">
                  No videos found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
