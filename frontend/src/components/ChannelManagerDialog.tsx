import { Loader2, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { useAddChannel, useChannels, useDeleteChannel } from "@/api/queries"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ChannelManagerDialog({ open, onOpenChange }: Props) {
  const { data: channels } = useChannels()
  const addChannel = useAddChannel()
  const deleteChannel = useDeleteChannel()
  const [input, setInput] = useState("")

  const submit = () => {
    const value = input.trim()
    if (!value) return
    addChannel.mutate(value, {
      onSuccess: (channel) => {
        toast.success(`Added ${channel.label}`)
        setInput("")
      },
      onError: (error) => toast.error(error.message),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Manage channels</DialogTitle>
          <DialogDescription>
            Add a channel by @handle, channel ID (UC…), or URL. The channel is
            verified on YouTube before being added.
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2">
          <Input
            placeholder="@handle, UC… or URL"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            disabled={addChannel.isPending}
          />
          <Button onClick={submit} disabled={addChannel.isPending || !input.trim()}>
            {addChannel.isPending && <Loader2 className="animate-spin" />}
            Add
          </Button>
        </div>

        <Separator />

        <ul className="space-y-1">
          {(channels ?? []).map((channel) => (
            <li
              key={channel.id}
              className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
            >
              <div className="min-w-0">
                <div className="truncate font-medium">{channel.label}</div>
                <div className="text-muted-foreground truncate text-xs">
                  {channel.input}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${channel.label}`}
                disabled={deleteChannel.isPending}
                onClick={() =>
                  deleteChannel.mutate(channel.id, {
                    onSuccess: () => toast.success(`Removed ${channel.label}`),
                    onError: (error) => toast.error(error.message),
                  })
                }
              >
                <Trash2 className="text-destructive" />
              </Button>
            </li>
          ))}
          {channels && channels.length === 0 && (
            <li className="text-muted-foreground py-2 text-center text-sm">
              No channels yet.
            </li>
          )}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
