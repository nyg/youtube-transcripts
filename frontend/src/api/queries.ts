import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import { api } from "./client"
import type {
  Channel,
  Estimate,
  EstimateRequest,
  Job,
  Meta,
  Prompt,
  Summary,
  SummaryDetail,
  VideoList,
} from "./types"

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/meta"),
    staleTime: Infinity,
  })
}

export function useChannels() {
  return useQuery({
    queryKey: ["channels"],
    queryFn: () => api<Channel[]>("/api/channels"),
  })
}

export function useAddChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { input: string; promptName: string; notifyEmails: string[] }) =>
      api<Channel>("/api/channels", {
        method: "POST",
        body: JSON.stringify({
          input: vars.input,
          prompt_name: vars.promptName,
          notify_emails: vars.notifyEmails,
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channels"] }),
  })
}

export function useDeleteChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (channelId: number) =>
      api<void>(`/api/channels/${channelId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channels"] }),
  })
}

export function useUpdateChannel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      channelId: number
      promptName?: string
      notifyEmails?: string[]
    }) =>
      api<Channel>(`/api/channels/${vars.channelId}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...(vars.promptName !== undefined && { prompt_name: vars.promptName }),
          ...(vars.notifyEmails !== undefined && { notify_emails: vars.notifyEmails }),
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channels"] }),
  })
}

export function usePrompts() {
  return useQuery({
    queryKey: ["prompts"],
    queryFn: () => api<Prompt[]>("/api/prompts"),
  })
}

export function useAddPrompt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { name: string; text: string; estimatedOutputTokens: number }) =>
      api<Prompt>("/api/prompts", {
        method: "POST",
        body: JSON.stringify({
          name: vars.name,
          text: vars.text,
          estimated_output_tokens: vars.estimatedOutputTokens,
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  })
}

export function useUpdatePrompt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      promptId: number
      text?: string
      estimatedOutputTokens?: number
    }) =>
      api<Prompt>(`/api/prompts/${vars.promptId}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...(vars.text !== undefined && { text: vars.text }),
          ...(vars.estimatedOutputTokens !== undefined && {
            estimated_output_tokens: vars.estimatedOutputTokens,
          }),
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  })
}

export function useDeletePrompt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (promptId: number) =>
      api<void>(`/api/prompts/${promptId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  })
}

export function useVideos(channelId: number) {
  return useQuery({
    queryKey: ["videos", channelId],
    queryFn: () => api<VideoList>(`/api/channels/${channelId}/videos`),
    // A listing takes yt-dlp a few seconds — don't refire on window focus.
    staleTime: 5 * 60 * 1000,
  })
}

export function useCreateEstimate() {
  return useMutation({
    mutationFn: (body: EstimateRequest) =>
      api<Estimate>("/api/estimates", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  })
}

export function useCreateJob() {
  return useMutation({
    mutationFn: (estimateId: string) =>
      api<{ job_id: string }>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({ estimate_id: estimateId }),
      }),
  })
}

export function useJob(jobId: string) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) =>
      query.state.data?.status === "done" ? false : 1000,
  })
}

export function useSummaries(channelId?: number) {
  return useQuery({
    queryKey: ["summaries", channelId ?? "all"],
    queryFn: () =>
      api<Summary[]>(
        channelId === undefined
          ? "/api/summaries"
          : `/api/summaries?channel_id=${channelId}`,
      ),
  })
}

export function useSummaryDetail(videoId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["summary", videoId],
    queryFn: () => api<SummaryDetail>(`/api/summaries/${videoId}`),
    enabled,
    staleTime: Infinity,
  })
}
