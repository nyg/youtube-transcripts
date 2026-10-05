import { Clock } from "lucide-react"

import { useMeta } from "@/api/queries"
import { formatDateTime } from "@/lib/datetime"

const usd = (n: number) => `$${n.toFixed(2)}`

/** Subtle indicator, only shown when the scheduled monitor is enabled. */
export function MonitorStatus() {
  const { data: meta } = useMeta()
  if (!meta?.monitoring_enabled) return null

  const budget =
    meta.daily_budget_usd > 0
      ? `${usd(meta.spend_today_usd)} of ${usd(meta.daily_budget_usd)} spent today`
      : `${usd(meta.spend_today_usd)} spent today`

  // The schedule is a cron expression; show the next fire time in local time.
  const title = meta.monitor_next_run
    ? `Next check: ${formatDateTime(meta.monitor_next_run)}`
    : undefined

  return (
    <span
      className="text-muted-foreground inline-flex items-center gap-1.5 text-xs"
      title={title}
    >
      <Clock className="size-3.5" />
      Monitoring on · {budget}
    </span>
  )
}
