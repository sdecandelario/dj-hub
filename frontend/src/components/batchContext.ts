import { createContext, useContext } from 'react'
import type { Batch } from '../api'

// `applied` counts applied batches, so pages can drop selections whose paths just changed.
export type Ctx = {
  preview: (make: () => Promise<Batch>) => Promise<void>
  /** Plan a change of this kind and open the dialog. */
  plan: (kind: Batch['kind'], payload: object) => Promise<void>
  applied: number
}
export const BatchContext = createContext<Ctx>({ preview: async () => {}, plan: async () => {}, applied: 0 })
export const useBatch = () => useContext(BatchContext)
