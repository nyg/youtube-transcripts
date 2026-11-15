import { useState } from 'react'

export function useSyncedState<T>(value: T, source: unknown = value) {
   const [state, setState] = useState(value)
   const [syncedSource, setSyncedSource] = useState(source)

   if (syncedSource !== source) {
      setSyncedSource(source)
      setState(value)
   }

   return [state, setState] as const
}
