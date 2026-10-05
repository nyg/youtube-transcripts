import { Loader2, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import {
  useAddChannel,
  useChannels,
  useDeleteChannel,
  usePrompts,
  useUpdateChannel,
} from "@/api/queries"
import type { Channel, Prompt } from "@/api/types"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ChannelManagerDialog({ open, onOpenChange }: Props) {
  const { data: channels } = useChannels()
  const { data: prompts } = usePrompts()
  const addChannel = useAddChannel()
  const [input, setInput] = useState("")
  const [promptName, setPromptName] = useState("")

  const noPrompts = !!prompts && prompts.length === 0

  // Default the new-channel prompt to the first available one.
  useEffect(() => {
    if (!promptName && prompts && prompts.length > 0) setPromptName(prompts[0].name)
  }, [prompts, promptName])

  const submit = () => {
    const value = input.trim()
    if (!value || !promptName) return
    addChannel.mutate(
      { input: value, promptName, notifyEmails: [] },
      {
        onSuccess: (channel) => {
          toast.success(`Added ${channel.label}`)
          setInput("")
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Channels</DialogTitle>
          <DialogDescription>
            Add a channel by @handle, channel ID or URL, and choose its prompt.
          </DialogDescription>
        </DialogHeader>

        {noPrompts && (
          <p className="text-muted-foreground text-sm">
            Add a prompt in Prompts first.
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <Input
            className="min-w-48 flex-1"
            placeholder="@handle, UC… or URL"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            disabled={addChannel.isPending || noPrompts}
          />
          <Select
            value={promptName}
            onValueChange={setPromptName}
            disabled={addChannel.isPending || noPrompts}
          >
            <SelectTrigger className="h-8 w-40" aria-label="Prompt for new channel">
              <SelectValue placeholder="Prompt" />
            </SelectTrigger>
            <SelectContent>
              {(prompts ?? []).map((p) => (
                <SelectItem key={p.id} value={p.name}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={submit}
            disabled={addChannel.isPending || !input.trim() || !promptName}
          >
            {addChannel.isPending && <Loader2 className="animate-spin" />}
            Add
          </Button>
        </div>

        <Separator />

        <ul className="space-y-2">
          {(channels ?? []).map((channel) => (
            <ChannelRow key={channel.id} channel={channel} prompts={prompts ?? []} />
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

function ChannelRow({ channel, prompts }: { channel: Channel; prompts: Prompt[] }) {
  const deleteChannel = useDeleteChannel()
  const updateChannel = useUpdateChannel()
  const [emails, setEmails] = useState(channel.notify_emails.join(", "))

  // Keep the local field in sync if the channel changes elsewhere.
  useEffect(() => {
    setEmails(channel.notify_emails.join(", "))
  }, [channel.notify_emails])

  const commitEmails = () => {
    const parsed = emails
      .split(/[,\n]/)
      .map((e) => e.trim())
      .filter(Boolean)
    if (parsed.join(",") === channel.notify_emails.join(",")) return // no-op
    updateChannel.mutate(
      { channelId: channel.id, notifyEmails: parsed },
      {
        onSuccess: () => toast.success(`Updated ${channel.label}`),
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <li className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{channel.label}</div>
          <div className="text-muted-foreground truncate text-xs">{channel.input}</div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Delete ${channel.label}`}
          disabled={deleteChannel.isPending}
          onClick={() =>
            deleteChannel.mutate(channel.id, {
              onSuccess: () => toast.success(`Deleted ${channel.label}`),
              onError: (error) => toast.error(error.message),
            })
          }
        >
          <Trash2 className="text-destructive" />
        </Button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label className="text-xs">Prompt</Label>
          <Select
            value={channel.prompt_name ?? undefined}
            onValueChange={(v) =>
              updateChannel.mutate(
                { channelId: channel.id, promptName: v },
                { onError: (error) => toast.error(error.message) },
              )
            }
          >
            <SelectTrigger className="h-8 w-40" aria-label={`Prompt for ${channel.label}`}>
              <SelectValue placeholder="Select a prompt" />
            </SelectTrigger>
            <SelectContent>
              {prompts.map((p) => (
                <SelectItem key={p.id} value={p.name}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-48 flex-1 space-y-1">
          <Label className="text-xs" htmlFor={`emails-${channel.id}`}>
            Email new summaries to
          </Label>
          <Input
            id={`emails-${channel.id}`}
            placeholder="you@example.com, friend@example.com"
            value={emails}
            onChange={(e) => setEmails(e.target.value)}
            onBlur={commitEmails}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          />
        </div>
      </div>
    </li>
  )
}
