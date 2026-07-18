import type { Channel } from "@/api/types"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

interface Props {
  channels: Channel[]
  value: number | null
  onChange: (channelId: number) => void
}

export function ChannelSelect({ channels, value, onChange }: Props) {
  if (channels.length === 0) return null
  return (
    <Select
      value={value !== null ? String(value) : undefined}
      onValueChange={(v) => onChange(Number(v))}
    >
      <SelectTrigger className="w-56">
        <SelectValue placeholder="Select a channel" />
      </SelectTrigger>
      <SelectContent>
        {channels.map((channel) => (
          <SelectItem key={channel.id} value={String(channel.id)}>
            {channel.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
