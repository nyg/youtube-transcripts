import { Loader2, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { useAddPrompt, useDeletePrompt, usePrompts, useUpdatePrompt } from "@/api/queries"
import type { Prompt } from "@/api/types"
import { EffortSelect, ModelSelect } from "@/components/ModelSettingsSelects"
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
  const [model, setModel] = useState("")
  const [effort, setEffort] = useState("")
  const [maxTokens, setMaxTokens] = useState(DEFAULT_MAX_OUTPUT_TOKENS)
  const [entityKind, setEntityKind] = useState("")
  const [labels, setLabels] = useState("")

  const canAdd =
    !!name.trim() &&
    !!text.trim() &&
    !!model &&
    !!effort &&
    isTokenCount(tokens) &&
    isTokenCount(maxTokens)

  const submit = () => {
    if (!canAdd) return
    addPrompt.mutate(
      {
        name: name.trim(),
        text: text.trim(),
        estimatedOutputTokens: parseInt(tokens, 10),
        model,
        effort,
        maxOutputTokens: parseInt(maxTokens, 10),
        entityKind: entityKind.trim(),
        stanceLabels: splitLabels(labels),
      },
      {
        onSuccess: (p) => {
          toast.success(`Added ${p.name}`)
          setName("")
          setText("")
          setTokens("2000")
          setModel("")
          setEffort("")
          setMaxTokens(DEFAULT_MAX_OUTPUT_TOKENS)
          setEntityKind("")
          setLabels("")
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Manage prompts</DialogTitle>
          <DialogDescription>
            A prompt is the instruction sent to Claude to summarize a video.
            Channels each choose one. Every prompt runs on the model and effort
            you choose for it. “Est. output” is the assumed output length used
            for cost estimates; “Max output” is the hard cap on thinking plus
            response. Give a prompt an entity kind and stance labels to also
            extract mentions (entity, stance, quote) into the Mentions tab;
            leave the labels empty for a summary only.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Input
            placeholder="Prompt name (e.g. crypto-summary)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={addPrompt.isPending}
          />
          <div className="flex flex-wrap items-center gap-2">
            <ModelSelect
              label="Model for the new prompt"
              value={model}
              onChange={setModel}
              disabled={addPrompt.isPending}
            />
            <EffortSelect
              label="Effort for the new prompt"
              value={effort}
              onChange={setEffort}
              disabled={addPrompt.isPending}
            />
            <TokenField
              id="new-prompt-tokens"
              label="Est. output"
              value={tokens}
              onChange={setTokens}
              disabled={addPrompt.isPending}
            />
            <TokenField
              id="new-prompt-max-tokens"
              label="Max output"
              value={maxTokens}
              onChange={setMaxTokens}
              disabled={addPrompt.isPending}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Input
              className="w-40"
              placeholder="Entity kind (e.g. coin)"
              value={entityKind}
              onChange={(e) => setEntityKind(e.target.value)}
              disabled={addPrompt.isPending}
            />
            <Input
              className="min-w-40 flex-1"
              placeholder="Stance labels, comma-separated (e.g. bullish, bearish, neutral)"
              value={labels}
              onChange={(e) => setLabels(e.target.value)}
              disabled={addPrompt.isPending}
            />
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

const DEFAULT_MAX_OUTPUT_TOKENS = "8192"

function isTokenCount(value: string): boolean {
  const count = parseInt(value, 10)
  return Number.isFinite(count) && count >= 1
}

interface TokenFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  onCommit?: () => void
  disabled?: boolean
}

function TokenField({ id, label, value, onChange, onCommit, disabled }: TokenFieldProps) {
  return (
    <div className="flex items-center gap-1.5">
      <Label className="text-muted-foreground text-xs" htmlFor={id}>
        {label}
      </Label>
      <Input
        id={id}
        className="w-20"
        type="number"
        min={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onCommit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        disabled={disabled}
      />
    </div>
  )
}

function splitLabels(value: string): string[] {
  return value
    .split(",")
    .map((label) => label.trim())
    .filter(Boolean)
}

function PromptRow({ prompt }: { prompt: Prompt }) {
  const updatePrompt = useUpdatePrompt()
  const deletePrompt = useDeletePrompt()
  const [text, setText] = useState(prompt.text)
  const [tokens, setTokens] = useState(String(prompt.estimated_output_tokens))
  const [maxTokens, setMaxTokens] = useState(String(prompt.max_output_tokens))
  const [entityKind, setEntityKind] = useState(prompt.entity_kind ?? "")
  const [labels, setLabels] = useState(prompt.stance_labels.join(", "))

  useEffect(() => setText(prompt.text), [prompt.text])
  useEffect(() => setEntityKind(prompt.entity_kind ?? ""), [prompt.entity_kind])
  useEffect(() => setLabels(prompt.stance_labels.join(", ")), [prompt.stance_labels])
  useEffect(() => setTokens(String(prompt.estimated_output_tokens)), [prompt.estimated_output_tokens])
  useEffect(() => setMaxTokens(String(prompt.max_output_tokens)), [prompt.max_output_tokens])

  const update = (fields: Omit<Parameters<typeof updatePrompt.mutate>[0], "promptId">) =>
    updatePrompt.mutate(
      { promptId: prompt.id, ...fields },
      {
        onSuccess: () => toast.success(`Updated ${prompt.name}`),
        onError: (error) => toast.error(error.message),
      },
    )

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
    if (!isTokenCount(tokens) || tok === prompt.estimated_output_tokens) {
      setTokens(String(prompt.estimated_output_tokens))
      return
    }
    update({ estimatedOutputTokens: tok })
  }

  const commitMaxTokens = () => {
    const tok = parseInt(maxTokens, 10)
    if (!isTokenCount(maxTokens) || tok === prompt.max_output_tokens) {
      setMaxTokens(String(prompt.max_output_tokens))
      return
    }
    update({ maxOutputTokens: tok })
  }

  const commitEntityKind = () => {
    const kind = entityKind.trim()
    if (kind === (prompt.entity_kind ?? "")) return
    updatePrompt.mutate(
      { promptId: prompt.id, entityKind: kind },
      {
        onSuccess: () => toast.success(`Updated ${prompt.name}`),
        onError: (error) => toast.error(error.message),
      },
    )
  }

  const commitLabels = () => {
    const next = splitLabels(labels)
    if (next.join("\u0000") === prompt.stance_labels.join("\u0000")) return
    updatePrompt.mutate(
      { promptId: prompt.id, stanceLabels: next },
      {
        onSuccess: () => toast.success(`Updated ${prompt.name}`),
        onError: (error) => {
          setLabels(prompt.stance_labels.join(", "))
          toast.error(error.message)
        },
      },
    )
  }

  return (
    <li className="space-y-2 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="truncate font-medium">{prompt.name}</div>
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
      <div className="flex flex-wrap items-center gap-2">
        <ModelSelect
          label={`Model for ${prompt.name}`}
          value={prompt.model ?? ""}
          onChange={(model) => update({ model })}
          invalid={!prompt.model}
        />
        <EffortSelect
          label={`Effort for ${prompt.name}`}
          value={prompt.effort ?? ""}
          onChange={(effort) => update({ effort })}
          invalid={!prompt.effort}
        />
        <TokenField
          id={`tokens-${prompt.id}`}
          label="Est. output"
          value={tokens}
          onChange={setTokens}
          onCommit={commitTokens}
        />
        <TokenField
          id={`max-tokens-${prompt.id}`}
          label="Max output"
          value={maxTokens}
          onChange={setMaxTokens}
          onCommit={commitMaxTokens}
        />
      </div>
      {(!prompt.model || !prompt.effort) && (
        <p className="text-destructive text-xs">
          Choose a model and an effort — this prompt cannot run until both are set.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Input
          className="w-40"
          aria-label={`Entity kind for ${prompt.name}`}
          placeholder="Entity kind"
          value={entityKind}
          onChange={(e) => setEntityKind(e.target.value)}
          onBlur={commitEntityKind}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        />
        <Input
          className="min-w-40 flex-1"
          aria-label={`Stance labels for ${prompt.name}`}
          placeholder="Stance labels, comma-separated"
          value={labels}
          onChange={(e) => setLabels(e.target.value)}
          onBlur={commitLabels}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        />
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
