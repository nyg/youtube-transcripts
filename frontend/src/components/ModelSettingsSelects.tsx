import { useMeta } from "@/api/queries"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

interface Props {
  value: string
  onChange: (value: string) => void
  label: string
  disabled?: boolean
  invalid?: boolean
}

export function ModelSelect({ value, onChange, label, disabled, invalid }: Props) {
  const { data: meta } = useMeta()
  const models = meta?.models ?? []
  const unpriced = !!value && !!meta && !models.includes(value)

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="w-44" aria-label={label} aria-invalid={invalid}>
        <SelectValue placeholder="Model" />
      </SelectTrigger>
      <SelectContent>
        {unpriced && <SelectItem value={value}>{value} (no pricing)</SelectItem>}
        {models.map((model) => (
          <SelectItem key={model} value={model}>
            {model}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function EffortSelect({ value, onChange, label, disabled, invalid }: Props) {
  const { data: meta } = useMeta()

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="w-24" aria-label={label} aria-invalid={invalid}>
        <SelectValue placeholder="Effort" />
      </SelectTrigger>
      <SelectContent>
        {(meta?.efforts ?? []).map((effort) => (
          <SelectItem key={effort} value={effort}>
            {effort}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
