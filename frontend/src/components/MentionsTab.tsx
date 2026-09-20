import { Fragment, useMemo, useState } from "react"

import { useEntities } from "@/api/queries"
import { MentionTimeline } from "@/components/MentionTimeline"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatPublished } from "@/lib/datetime"
import { stanceClass } from "@/lib/stance"

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "all", label: "All time" },
]

export function MentionsTab({ channelId }: { channelId: number }) {
  const [period, setPeriod] = useState("30")
  const [filter, setFilter] = useState("")
  const [allChannels, setAllChannels] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const since = useMemo(() => {
    if (period === "all") return undefined
    return new Date(Date.now() - Number(period) * 86_400_000).toISOString()
  }, [period])

  const scope = allChannels ? undefined : channelId
  const { data: entities, isLoading } = useEntities(scope, since)

  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!entities) return []
    if (!needle) return entities
    return entities.filter((entity) => entity.entity.toLowerCase().includes(needle))
  }, [entities, filter])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter entities…"
          className="max-w-56"
        />
        <Select value={period} onValueChange={setPeriod}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex items-center gap-2">
          <Checkbox
            id="mentions-all-channels"
            checked={allChannels}
            onCheckedChange={(checked) => setAllChannels(checked === true)}
          />
          <Label htmlFor="mentions-all-channels" className="font-normal">
            All channels
          </Label>
        </div>
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {!isLoading && rows.length === 0 && (
        <p className="text-muted-foreground py-16 text-center">
          No mentions yet. Give the channel’s prompt an entity kind and stance labels in
          “Manage prompts”, then process (or reprocess) videos.
        </p>
      )}

      {!isLoading && rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Entity</TableHead>
              <TableHead>Latest stance</TableHead>
              <TableHead>Previously</TableHead>
              <TableHead>Last mentioned</TableHead>
              <TableHead className="text-right">Videos</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((entity) => {
              const open = expanded === entity.entity_key
              return (
                <Fragment key={entity.entity_key}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => setExpanded(open ? null : entity.entity_key)}
                  >
                    <TableCell className="font-medium">{entity.entity}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={stanceClass(entity.latest_stance)}>
                        {entity.latest_stance}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {entity.previous_stance ? (
                        <span className="text-muted-foreground flex items-center gap-1 text-sm">
                          {entity.previous_stance}
                          <span aria-hidden>→</span>
                          <span className="text-foreground">changed</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground text-sm">unchanged</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatPublished(entity.latest_at)}
                    </TableCell>
                    <TableCell className="text-right">{entity.video_count}</TableCell>
                  </TableRow>
                  {open && (
                    <TableRow>
                      <TableCell colSpan={5} className="bg-muted/40">
                        <MentionTimeline
                          channelId={scope}
                          entity={entity.entity}
                          since={since}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
