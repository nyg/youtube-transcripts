import { Loader2, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { useAddPrompt, useDeletePrompt, usePrompts, useUpdatePrompt } from "@/api/queries"
import type { Prompt } from "@/api/types"
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
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function PromptManagerDialog({ open, onOpenChange }: Props) {
  const { data: prompts } = usePrompts()
  const addPrompt = useAddPrompt()
  const [name, setName] = useState("")
  const [text, setText] = useState("")
  const [tokens, setTokens] = useState("2000")

  const tokensValid = Number.isFinite(parseInt(tokens, 10)) && parseInt(tokens, 10) >= 1
  const canAdd = !!name.trim() && !!text.trim() && tokensValid

  const submit = () => {
    if (!canAdd) return
    addPrompt.mutate(
      { name: name.trim(), text: text.trim(), estimatedOutputTokens: parseInt(tokens, 10) },
      {
        onSuccess: (p) => {
          toast.success(`Added ${p.name}`)
          setName("")
          setText("")
          setTokens("2000")
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Manage prompts</DialogTitle>
          <DialogDescription>
            A prompt is the instruction sent to Claude to summarize a video.
            Channels each choose one. “Output tokens” is the assumed response
            length used for cost estimates.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Input
              className="min-w-40 flex-1"
              placeholder="Prompt name (e.g. crypto-summary)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={addPrompt.isPending}
            />
            <div className="flex items-center gap-1.5">
              <Label className="text-muted-foreground text-xs" htmlFor="new-prompt-tokens">
                Output tokens
              </Label>
              <Input
                id="new-prompt-tokens"
                className="w-24"
                type="number"
                min={1}
                value={tokens}
                onChange={(e) => setTokens(e.target.value)}
                disabled={addPrompt.isPending}
              />
            </div>
          </div>
          <Textarea
            placeholder="You are given the full transcript of a YouTube video. Summarize…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={addPrompt.isPending}
          />
          <div className="flex justify-end">
            <Button onClick={submit} disabled={addPrompt.isPending || !canAdd}>
              {addPrompt.isPending && <Loader2 className="animate-spin" />}
              Add prompt
            </Button>
          </div>
        </div>

        <Separator />

        <ul className="space-y-2">
          {(prompts ?? []).map((prompt) => (
            <PromptRow key={prompt.id} prompt={prompt} />
          ))}
          {prompts && prompts.length === 0 && (
            <li className="text-muted-foreground py-2 text-center text-sm">
              No prompts yet.
            </li>
          )}
        </ul>
      </DialogContent>
    </Dialog>
  )
}

function PromptRow({ prompt }: { prompt: Prompt }) {
  const updatePrompt = useUpdatePrompt()
  const deletePrompt = useDeletePrompt()
  const [text, setText] = useState(prompt.text)
  const [tokens, setTokens] = useState(String(prompt.estimated_output_tokens))

  useEffect(() => setText(prompt.text), [prompt.text])
  useEffect(() => setTokens(String(prompt.estimated_output_tokens)), [prompt.estimated_output_tokens])

  const commitText = () => {
    const t = text.trim()
    if (!t || t === prompt.text) {
      setText(prompt.text) // revert an emptied field
      return
    }
    updatePrompt.mutate(
      { promptId: prompt.id, text: t },
      {
        onSuccess: () => toast.success(`Updated ${prompt.name}`),
        onError: (error) => toast.error(error.message),
      },
    )
  }

  const commitTokens = () => {
    const tok = parseInt(tokens, 10)
    if (!Number.isFinite(tok) || tok < 1 || tok === prompt.estimated_output_tokens) {
      setTokens(String(prompt.estimated_output_tokens))
      return
    }
    updatePrompt.mutate(
      { promptId: prompt.id, estimatedOutputTokens: tok },
      {
        onSuccess: () => toast.success(`Updated ${prompt.name}`),
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <li className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="truncate font-medium">{prompt.name}</div>
        <div className="flex items-center gap-2">
          <Label className="text-muted-foreground text-xs" htmlFor={`tokens-${prompt.id}`}>
            Output tokens
          </Label>
          <Input
            id={`tokens-${prompt.id}`}
            className="w-24"
            type="number"
            min={1}
            value={tokens}
            onChange={(e) => setTokens(e.target.value)}
            onBlur={commitTokens}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${prompt.name}`}
            disabled={deletePrompt.isPending}
            onClick={() =>
              deletePrompt.mutate(prompt.id, {
                onSuccess: () => toast.success(`Removed ${prompt.name}`),
                onError: (error) => toast.error(error.message),
              })
            }
          >
            <Trash2 className="text-destructive" />
          </Button>
        </div>
      </div>
      <Textarea
        aria-label={`Text for ${prompt.name}`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commitText}
      />
    </li>
  )
}
