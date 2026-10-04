import { Loader2, RefreshCw } from "lucide-react"
import { type ReactNode, useState } from "react"
import { toast } from "sonner"

import { useMeta, useRefreshModels, useSettings, useUpdateSettings } from "@/api/queries"
import type { Settings } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type Draft = Record<string, string | boolean>

interface Field {
  path: string
  label: string
  kind: "int" | "float" | "text"
  min?: number
  hint?: string
  wide?: boolean
}

const YOUTUBE_FIELDS: Field[] = [
  { path: "max_videos_fetch", label: "Videos listed per channel", kind: "int", min: 1 },
  {
    path: "youtube_request_interval",
    label: "Seconds between YouTube requests",
    kind: "float",
    min: 0,
    hint: "Raise it when YouTube answers HTTP 429.",
  },
  {
    path: "transcript_languages",
    label: "Transcript languages",
    kind: "text",
    hint: "Comma-separated, in order of preference.",
  },
  {
    path: "cookies_file",
    label: "Cookies file",
    kind: "text",
    hint: "Optional path on the server to Netscape-format cookies of a logged-in session.",
  },
]

const ASK_FIELDS: Field[] = [
  {
    path: "ask.max_context_tokens",
    label: "Context ceiling (tokens)",
    kind: "int",
    min: 1000,
    hint: "Most mentions, summaries and excerpts sent with a question. More costs more.",
  },
  {
    path: "ask.estimated_output_tokens",
    label: "Assumed answer length (tokens)",
    kind: "int",
    min: 1,
  },
  {
    path: "ask.max_output_tokens",
    label: "Max output (tokens)",
    kind: "int",
    min: 1,
    hint: "Caps thinking plus answer.",
  },
]

const MONITORING_FIELDS: Field[] = [
  {
    path: "monitoring.schedule",
    label: "Schedule",
    kind: "text",
    hint: "Cron expression in the server's local time, e.g. 0 8,20 * * * for 08:00 and 20:00.",
    wide: true,
  },
  {
    path: "monitoring.max_videos_check",
    label: "Recent videos checked per channel",
    kind: "int",
    min: 1,
  },
  {
    path: "monitoring.max_age_hours",
    label: "Ignore videos older than (hours)",
    kind: "int",
    min: 0,
    hint: "0 = no limit.",
  },
  {
    path: "monitoring.daily_budget_usd",
    label: "Daily budget (USD)",
    kind: "float",
    min: 0,
    hint: "0 = unlimited.",
  },
  { path: "monitoring.subject_prefix", label: "Digest subject prefix", kind: "text" },
  { path: "monitoring.resend_from", label: "Digest sender", kind: "text", wide: true },
]

const priceField = (family: string, side: "input" | "output"): Field => ({
  path: `pricing.${family}.${side}`,
  label: `${side === "input" ? "Input" : "Output"} price of ${family}`,
  kind: "float",
  min: 0,
})

function toDraft(settings: Settings): Draft {
  const draft: Draft = {}
  const flatten = (value: unknown, path: string) => {
    if (Array.isArray(value)) draft[path] = value.join(", ")
    else if (typeof value === "boolean") draft[path] = value
    else if (value !== null && typeof value === "object")
      for (const [key, child] of Object.entries(value))
        flatten(child, path ? `${path}.${key}` : key)
    else draft[path] = value == null ? "" : String(value)
  }
  flatten(settings, "")
  return draft
}

function toSettings(draft: Draft, families: string[]): Settings {
  const text = (path: string) => String(draft[path] ?? "").trim()
  const number = (path: string) => Number(text(path))
  return {
    max_videos_fetch: number("max_videos_fetch"),
    transcript_languages: text("transcript_languages")
      .split(",")
      .map((language) => language.trim())
      .filter(Boolean),
    youtube_request_interval: number("youtube_request_interval"),
    cookies_file: text("cookies_file") || null,
    pricing: Object.fromEntries(
      families.map((family) => [
        family,
        {
          input: number(`pricing.${family}.input`),
          output: number(`pricing.${family}.output`),
        },
      ]),
    ),
    monitoring: {
      enabled: draft["monitoring.enabled"] === true,
      schedule: text("monitoring.schedule"),
      run_on_start: draft["monitoring.run_on_start"] === true,
      max_videos_check: number("monitoring.max_videos_check"),
      max_age_hours: number("monitoring.max_age_hours"),
      daily_budget_usd: number("monitoring.daily_budget_usd"),
      resend_from: text("monitoring.resend_from"),
      subject_prefix: text("monitoring.subject_prefix"),
    },
    ask: {
      max_context_tokens: number("ask.max_context_tokens"),
      estimated_output_tokens: number("ask.estimated_output_tokens"),
      max_output_tokens: number("ask.max_output_tokens"),
    },
  }
}

function isValid(field: Field, draft: Draft): boolean {
  if (field.kind === "text") return true
  const raw = String(draft[field.path] ?? "").trim()
  const value = Number(raw)
  if (raw === "" || !Number.isFinite(value) || value < (field.min ?? 0)) return false
  return field.kind === "float" || Number.isInteger(value)
}

export function SettingsDialog({ open, onOpenChange }: Props) {
  const { data: settings, error } = useSettings(open)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
        </DialogHeader>
        {error && (
          <p className="text-destructive">Could not load the settings: {error.message}</p>
        )}
        {settings && <SettingsForm settings={settings} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function SettingsForm({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const { data: meta } = useMeta()
  const updateSettings = useUpdateSettings()
  const refreshModels = useRefreshModels()
  const [draft, setDraft] = useState(() => toDraft(settings))

  const models = meta?.models ?? []
  const families = Object.keys(settings.pricing)
  const tabs = [
    {
      value: "models",
      label: "Models",
      fields: families.flatMap((family) => [
        priceField(family, "input"),
        priceField(family, "output"),
      ]),
    },
    { value: "youtube", label: "YouTube", fields: YOUTUBE_FIELDS },
    { value: "ask", label: "Ask", fields: ASK_FIELDS },
    { value: "monitoring", label: "Monitoring", fields: MONITORING_FIELDS },
  ]
  const hasInvalid = (fields: Field[]) => fields.some((field) => !isValid(field, draft))
  const canSave = !tabs.some((tab) => hasInvalid(tab.fields))

  const set = (path: string, value: string | boolean) =>
    setDraft((current) => ({ ...current, [path]: value }))

  const save = () => {
    if (!canSave) return
    updateSettings.mutate(toSettings(draft, families), {
      onSuccess: () => {
        toast.success("Settings saved")
        onDone()
      },
      onError: (error) => toast.error(error.message),
    })
  }

  const refresh = () =>
    refreshModels.mutate(undefined, {
      onSuccess: () => toast.success("Model list refreshed"),
      onError: (error) => toast.error(error.message),
    })

  return (
    <>
      <Tabs defaultValue="models">
        <TabsList>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
              {hasInvalid(tab.fields) && (
                <span className="bg-destructive size-1.5 rounded-full" title="Invalid value" />
              )}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="grid pt-2">
          <Panel value="models">
            <p className="text-muted-foreground text-xs sm:col-span-2">
              Prices are in USD per million tokens. Update them manually when a model
              changes.
            </p>
            <div className="space-y-2 sm:col-span-2">
              <div className="flex gap-x-3 text-xs font-medium" aria-hidden>
                <span className="flex-1" />
                <span className="w-24">Input $</span>
                <span className="w-24">Output $</span>
              </div>
              <ul className="space-y-2">
                {models.map((model) => (
                  <li key={model.family} className="space-y-1">
                    <div className="flex items-center gap-x-3">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium capitalize">{model.family}</div>
                        <div className="text-muted-foreground text-xs">
                          {model.name} · {model.id}
                        </div>
                      </div>
                      {(["input", "output"] as const).map((side) => (
                        <SettingField
                          key={side}
                          className="w-24"
                          field={priceField(model.family, side)}
                          draft={draft}
                          onChange={set}
                          hideLabel
                        />
                      ))}
                    </div>
                    {!model.price_confirmed && (
                      <p className="text-destructive text-xs">
                        New model — check its price, then save.
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            <div className="sm:col-span-2">
              <Button
                variant="outline"
                size="sm"
                onClick={refresh}
                disabled={refreshModels.isPending}
              >
                {refreshModels.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                Check for new models
              </Button>
            </div>
          </Panel>

          <Panel value="youtube">
            {YOUTUBE_FIELDS.map((field) => (
              <SettingField key={field.path} field={field} draft={draft} onChange={set} />
            ))}
          </Panel>

          <Panel value="ask">
            {ASK_FIELDS.map((field) => (
              <SettingField key={field.path} field={field} draft={draft} onChange={set} />
            ))}
          </Panel>

          <Panel value="monitoring">
            <Toggle
              path="monitoring.enabled"
              label="Check channels for new videos automatically"
              draft={draft}
              onChange={set}
            />
            <Toggle
              path="monitoring.run_on_start"
              label="Also check when the server starts"
              draft={draft}
              onChange={set}
            />
            {MONITORING_FIELDS.map((field) => (
              <SettingField key={field.path} field={field} draft={draft} onChange={set} />
            ))}
          </Panel>
        </div>
      </Tabs>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button onClick={save} disabled={!canSave || updateSettings.isPending}>
          {updateSettings.isPending && <Loader2 className="animate-spin" />}
          Save
        </Button>
      </div>
    </>
  )
}

function Panel({ value, children }: { value: string; children: ReactNode }) {
  return (
    // Every panel stays mounted in the same grid cell, so the dialog keeps the
    // height of the tallest one instead of jumping when the tab changes. Without
    // transition-none, a button's transition-all delays its hiding and it shows
    // through the next panel for a moment.
    <TabsContent
      value={value}
      forceMount
      className="col-start-1 row-start-1 grid content-start gap-3 data-[state=inactive]:invisible data-[state=inactive]:**:transition-none sm:grid-cols-2"
    >
      {children}
    </TabsContent>
  )
}

interface ControlProps {
  draft: Draft
  onChange: (path: string, value: string | boolean) => void
}

function SettingField({
  field,
  draft,
  onChange,
  className,
  hideLabel,
}: ControlProps & { field: Field; className?: string; hideLabel?: boolean }) {
  const id = `setting-${field.path}`
  const numeric = field.kind !== "text"
  return (
    <div className={cn("space-y-1", field.wide && "sm:col-span-2", className)}>
      <Label className={cn("text-xs", hideLabel && "sr-only")} htmlFor={id}>
        {field.label}
      </Label>
      <Input
        id={id}
        type={numeric ? "number" : "text"}
        min={field.min}
        step={field.kind === "float" ? "any" : undefined}
        value={String(draft[field.path] ?? "")}
        onChange={(e) => onChange(field.path, e.target.value)}
        aria-invalid={!isValid(field, draft)}
      />
      {field.hint && <p className="text-muted-foreground ml-px pl-2.5 text-xs">{field.hint}</p>}
    </div>
  )
}

function Toggle({ path, label, draft, onChange }: ControlProps & { path: string; label: string }) {
  const id = `setting-${path}`
  return (
    <div className="flex items-center gap-2">
      <Checkbox
        id={id}
        checked={draft[path] === true}
        onCheckedChange={(checked) => onChange(path, checked === true)}
      />
      <Label htmlFor={id} className="font-normal">
        {label}
      </Label>
    </div>
  )
}
