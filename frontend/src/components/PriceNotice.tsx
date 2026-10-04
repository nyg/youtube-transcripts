import { useMeta } from "@/api/queries"

export function PriceNotice({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { data: meta } = useMeta()
  const moved = (meta?.models ?? []).filter((model) => !model.price_confirmed)
  if (moved.length === 0) return null

  const names = moved.map((model) => model.name).join(", ")
  return (
    <button
      type="button"
      className="text-destructive text-xs underline-offset-2 hover:underline"
      onClick={onOpenSettings}
    >
      {moved.length === 1
        ? `${names} is new — check its price in Settings`
        : `${names} are new — check their prices in Settings`}
    </button>
  )
}
