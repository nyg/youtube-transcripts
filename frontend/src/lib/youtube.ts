export function youtubeAt(url: string | null, seconds: number | null): string | null {
  if (!url) return null
  if (seconds === null || seconds < 0) return url
  const separator = url.includes("?") ? "&" : "?"
  return `${url}${separator}t=${Math.floor(seconds)}s`
}
