'use client'

import { Database, FileSearch, Calculator, BarChart3, Lock } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Layer {
  id: number
  label: string
  icon: typeof Database
  enabled: boolean
}

export const LAYERS: Layer[] = [
  { id: 1, label: 'Browse Line Items',  icon: Database,   enabled: true },
  { id: 2, label: 'Read Footnotes',     icon: FileSearch, enabled: true },
  { id: 3, label: 'Build Ratios',       icon: Calculator, enabled: true },
  { id: 4, label: 'Ratio Dashboard',    icon: BarChart3,  enabled: true },
]

interface LayerNavProps {
  current: number
  onChange: (layer: number) => void
  hasData: boolean
}

export default function LayerNav({ current, onChange, hasData }: LayerNavProps) {
  return (
    <nav className="flex items-center gap-1 bg-white border border-gray-200 rounded-xl p-1">
      {LAYERS.map((layer) => {
        const Icon = layer.icon
        const isActive = current === layer.id
        const disabled = !layer.enabled || (!hasData && layer.id > 1)

        return (
          <button
            key={layer.id}
            onClick={() => !disabled && onChange(layer.id)}
            disabled={disabled}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              isActive && 'bg-brand-600 text-white shadow-sm',
              !isActive && !disabled && 'text-gray-600 hover:bg-gray-100',
              disabled && 'text-gray-300 cursor-not-allowed',
            )}
          >
            {disabled && !isActive ? (
              <Lock className="w-4 h-4" />
            ) : (
              <Icon className="w-4 h-4" />
            )}
            <span className="hidden sm:inline">
              Layer {layer.id}: {layer.label}
            </span>
            <span className="sm:hidden">L{layer.id}</span>
          </button>
        )
      })}
    </nav>
  )
}
