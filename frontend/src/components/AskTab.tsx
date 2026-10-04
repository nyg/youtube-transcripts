import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { ApiError } from "@/api/client"
import {
  useAskQuestion,
  useEstimateQuestion,
  useMeta,
  useQuestions,
} from "@/api/queries"
import { AnswerCard } from "@/components/AnswerCard"
import { EffortSelect, ModelSelect } from "@/components/ModelSettingsSelects"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "all", label: "All time" },
]

export function AskTab({ channelId }: { channelId: number }) {
  const [question, setQuestion] = useState("")
  const [period, setPeriod] = useState("30")
  const [allChannels, setAllChannels] = useState(false)
  const [storedModel, setStoredModel] = useState(() => localStorage.getItem("askModel") ?? "")
  const [effort, setEffort] = useState(() => localStorage.getItem("askEffort") ?? "")

  const { data: meta } = useMeta()
  const model = meta && !meta.models.includes(storedModel) ? "" : storedModel

  const estimateQuestion = useEstimateQuestion()
  const askQuestion = useAskQuestion()
  const scope = allChannels ? undefined : channelId
  const { data: history, isLoading } = useQuestions(scope)

  const since = useMemo(() => {
    if (period === "all") return undefined
    return new Date(Date.now() - Number(period) * 86_400_000).toISOString()
  }, [period])

  const estimate = estimateQuestion.data
  const canEstimate =
    question.trim().length > 3 && !!model && !!effort && !estimateQuestion.isPending

  const runEstimate = () => {
    if (!canEstimate) return
    estimateQuestion.mutate(
      { question: question.trim(), model, effort, channelId: scope, since },
      { onError: (error) => toast.error(error.message) },
    )
  }

  const chooseModel = (value: string) => {
    setStoredModel(value)
    localStorage.setItem("askModel", value)
    estimateQuestion.reset()
  }

  const chooseEffort = (value: string) => {
    setEffort(value)
    localStorage.setItem("askEffort", value)
    estimateQuestion.reset()
  }

  const approve = () => {
    if (!estimate) return
    askQuestion.mutate(estimate.estimate_id, {
      onSuccess: () => {
        estimateQuestion.reset()
        setQuestion("")
      },
      onError: (error) => {
        if (error instanceof ApiError && error.status === 410) {
          toast.error("Estimate expired — re-estimating")
          runEstimate()
          return
        }
        toast.error(error.message)
      },
    })
  }

  return (
    <div className="space-y-4">
      <Textarea
        value={question}
        onChange={(event) => {
          setQuestion(event.target.value)
          if (estimate) estimateQuestion.reset()
        }}
        placeholder="What did he say about Solana, and did his stance change?"
        disabled={askQuestion.isPending}
      />

      <div className="flex flex-wrap items-center gap-3">
        <Select value={period} onValueChange={setPeriod}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <ModelSelect label="Model for the answer" value={model} onChange={chooseModel} />
        <EffortSelect label="Effort for the answer" value={effort} onChange={chooseEffort} />
        <div className="flex items-center gap-2">
          <Checkbox
            id="ask-all-channels"
            checked={allChannels}
            onCheckedChange={(checked) => setAllChannels(checked === true)}
          />
          <Label htmlFor="ask-all-channels" className="font-normal">
            All channels
          </Label>
        </div>
        <Button
          variant="outline"
          className="ml-auto"
          onClick={runEstimate}
          disabled={!canEstimate}
        >
          {estimateQuestion.isPending && <Loader2 className="animate-spin" />}
          Estimate cost
        </Button>
      </div>

      {estimate && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3">
            <Badge variant="outline">{estimate.mention_count} mentions</Badge>
            <Badge variant="outline">{estimate.summary_count} summaries</Badge>
            <Badge variant="outline">{estimate.excerpt_count} excerpts</Badge>
            <Badge variant="outline">
              {estimate.input_tokens.toLocaleString()} input tokens
            </Badge>
            <Badge variant="outline">
              {estimate.model} · {estimate.effort}
            </Badge>
            <Button className="ml-auto" onClick={approve} disabled={askQuestion.isPending}>
              {askQuestion.isPending && <Loader2 className="animate-spin" />}
              Approve — ask Claude
              {estimate.cost_usd != null && ` ($${estimate.cost_usd.toFixed(4)})`}
            </Button>
          </CardContent>
        </Card>
      )}

      {askQuestion.isPending && <Skeleton className="h-32 w-full" />}

      {isLoading && <Skeleton className="h-24 w-full" />}

      {!isLoading && (history?.length ?? 0) === 0 && !askQuestion.isPending && (
        <p className="text-muted-foreground py-16 text-center">
          No questions yet. Answers are built from the mentions, summaries and transcript
          excerpts in the chosen period, and cite the video they came from.
        </p>
      )}

      <div className="space-y-4">
        {(history ?? []).map((item) => (
          <AnswerCard key={item.id} question={item} />
        ))}
      </div>
    </div>
  )
}
