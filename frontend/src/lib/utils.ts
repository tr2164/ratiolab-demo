import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function fmtNumber(val: number): string {
  const abs = Math.abs(val)
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(0)}M`
  if (abs >= 1e3) return `$${(val / 1e3).toFixed(0)}K`
  return `$${val.toFixed(0)}`
}

export function fmtYears(min: number | null, max: number | null): string {
  if (min == null && max == null) return '—'
  if (min === max || max == null) return `${min} yr`
  if (min == null) return `${max} yr`
  return `${min}–${max} yr`
}
