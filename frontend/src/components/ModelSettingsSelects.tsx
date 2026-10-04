import { useMeta, useModelChoice } from "@/api/queries"
import type { ClaudeModel } from "@/api/types"
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

const shortName = (model: ClaudeModel) => model.name.replace(/^Claude /, "")

export function ModelSelect({ value, onChange, label, disabled, invalid }: Props) {
  const { data: meta } = useMeta()
  const models = meta?.models ?? []
  const unavailable = !!value && !!meta && !models.some((model) => model.family === value)

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="w-36" aria-label={label} aria-invalid={invalid}>
        <SelectValue placeholder="Model" />
      </SelectTrigger>
      <SelectContent>
        {unavailable && <SelectItem value={value}>{value} (unavailable)</SelectItem>}
        {models.map((model) => (
          <SelectItem key={model.family} value={model.family}>
            {shortName(model)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

interface EffortProps extends Props {
  model: string
}

export function EffortSelect({ model, value, onChange, label, disabled, invalid }: EffortProps) {
  const choice = useModelChoice(model, value)
  const efforts = choice.model?.efforts ?? []
  const takesNone = !!choice.model && !choice.needsEffort

  return (
    <Select
      value={efforts.includes(value) ? value : ""}
      onValueChange={onChange}
      disabled={disabled || efforts.length === 0}
    >
      <SelectTrigger className="w-28" aria-label={label} aria-invalid={invalid}>
        <SelectValue placeholder={takesNone ? "No effort" : "Effort"} />
      </SelectTrigger>
      <SelectContent>
        {efforts.map((effort) => (
          <SelectItem key={effort} value={effort}>
            {effort}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
