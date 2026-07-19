import { Clock } from "lucide-react"

import { useMeta } from "@/api/queries"

const usd = (n: number) => `$${n.toFixed(2)}`

/** Subtle indicator, only shown when the hourly monitor is enabled. */
export function MonitorStatus() {
  const { data: meta } = useMeta()
  if (!meta?.monitoring_enabled) return null

  const budget =
    meta.daily_budget_usd > 0
      ? `${usd(meta.spend_today_usd)} / ${usd(meta.daily_budget_usd)} today`
      : `${usd(meta.spend_today_usd)} today`

  return (
    <span
      className="text-muted-foreground inline-flex items-center gap-1.5 text-xs"
      title="Automatic hourly monitoring is on"
    >
      <Clock className="size-3.5" />
      Auto-monitor on · {budget}
    </span>
  )
}
