// Stance labels are user-defined, so colours are derived from the label itself
// and stay stable across renders and prompts.
const PALETTE = [
  "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  "border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  "border-teal-500/40 bg-teal-500/10 text-teal-700 dark:text-teal-300",
]

export function stanceClass(stance: string): string {
  let hash = 0
  for (const char of stance.toLowerCase()) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  }
  return PALETTE[hash % PALETTE.length]
}
