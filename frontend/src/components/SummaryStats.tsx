import type { ReactNode } from "react"

import type { Summary } from "@/api/types"

const count = (value: number) => value.toLocaleString()

const percent = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : "0%"

function signedPercent(actual: number, assumed: number): string {
  const diff = Math.round(((actual - assumed) / assumed) * 100)
  return `${diff > 0 ? "+" : ""}${diff}%`
}

interface StatProps {
  label: string
  warn?: boolean
  children: ReactNode
}

function Stat({ label, warn, children }: StatProps) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={warn ? "text-destructive" : "text-foreground"}>{children}</dd>
    </>
  )
}

export function SummaryStats({ summary }: { summary: Summary }) {
  const {
    tokens_input: input,
    tokens_output: output,
    tokens_thinking: thinking,
    max_output_tokens: cap,
    estimated_output_tokens: estimated,
    duration_ms: duration,
  } = summary
  const truncated = summary.stop_reason === "max_tokens"

  return (
    <dl className="bg-muted text-muted-foreground grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-md p-3 text-xs">
      <Stat label="Model">
        {summary.model} · {summary.effort} effort
      </Stat>
      {input != null && <Stat label="Input">{count(input)} tokens</Stat>}
      {output != null && (
        <Stat label="Output">
          {count(output)} tokens
          {thinking != null &&
            ` = ${count(thinking)} thinking (${percent(thinking, output)}) + ${count(output - thinking)} response`}
        </Stat>
      )}
      {output != null && cap != null && (
        <Stat label="Output cap" warn={truncated}>
          {truncated
            ? `hit the cap of ${count(cap)} — response cut off`
            : `${percent(output, cap)} of ${count(cap)} used`}
        </Stat>
      )}
      {output != null && !!estimated && (
        <Stat label="Estimate">
          assumed {count(estimated)} output tokens, actual {count(output)} (
          {signedPercent(output, estimated)})
        </Stat>
      )}
      {duration != null && <Stat label="Duration">{(duration / 1000).toFixed(1)} s</Stat>}
    </dl>
  )
}
