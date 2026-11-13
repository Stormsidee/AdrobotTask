export type Option = { id: number; name: string }
export type Catalogs = Record<'domains' | 'groups' | 'sources' | 'offers', Option[]>
export type Config = { mode: 'demo' | 'keitaro' | 'readonly'; timezone: string; today: string; prefix: string }
export type OfferLink = { offer_id: number; share: number; state: string }
export type Stream = Option & { editable: boolean; offers: OfferLink[] }
export type Metrics = { clicks: number; conversions: number; cr: number | null }
export type Report = { rows: (Metrics & { offer_id: number })[]; total: Metrics }

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : 'Проверьте значения полей или попробуйте ещё раз.')
  }
  return response.json() as Promise<T>
}

export const errorText = (error: unknown) => error instanceof Error ? error.message : 'Не удалось выполнить запрос.'
