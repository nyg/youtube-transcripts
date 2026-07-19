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
    mutationFn: (input: string) =>
      api<Channel>("/api/channels", {
        method: "POST",
        body: JSON.stringify({ input }),
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
    mutationFn: (vars: { channelId: number; promptName: string | null }) =>
      api<Channel>(`/api/channels/${vars.channelId}`, {
        method: "PATCH",
        body: JSON.stringify({ prompt_name: vars.promptName }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channels"] }),
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
