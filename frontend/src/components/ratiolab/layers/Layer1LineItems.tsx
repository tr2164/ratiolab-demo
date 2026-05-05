'use client'

import { useState, useMemo } from 'react'
import { Search, ChevronRight, ChevronDown, Check, X, Info, Database, BarChart3, ArrowDownUp, HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { fmtNumber } from '@/lib/utils'
import type { StatementLineItem } from '@/services/api'

const STATEMENT_SECTIONS = [
  { key: 'balance_sheet', label: 'Balance Sheet', icon: Database },
  { key: 'income_statement', label: 'Income Statement', icon: BarChart3 },
  { key: 'cash_flow', label: 'Cash Flow Statement', icon: ArrowDownUp },
  { key: 'other', label: 'Other', icon: HelpCircle },
]

interface Layer1LineItemsProps {
  items: StatementLineItem[]
  categoryCounts: Record<string, number>
  selectedConcepts: Set<string>
  onToggleConcept: (concept: string) => void
  onNextLayer: () => void
}

export default function Layer1LineItems({
  items, categoryCounts, selectedConcepts, onToggleConcept, onNextLayer,
}: Layer1LineItemsProps) {
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const filtered = useMemo(() => {
    if (!search) return items
    const q = search.toLowerCase()
    return items.filter(
      (i) => i.label.toLowerCase().includes(q) || i.concept.toLowerCase().includes(q)
    )
  }, [items, search])

  const grouped = useMemo(() => {
    const groups: Record<string, StatementLineItem[]> = {}
    for (const section of STATEMENT_SECTIONS) {
      groups[section.key] = []
    }
    for (const item of filtered) {
      const key = item.category in groups ? item.category : 'other'
      groups[key].push(item)
    }
    return groups
  }, [filtered])

  const toggleSection = (key: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const selectedCount = selectedConcepts.size

  return (
    <div className="space-y-4">
      {/* Coaching bar */}
      <div className="coaching-panel">
        <div className="flex items-start gap-2">
          <Info className="w-4 h-4 text-brand-500 shrink-0 mt-0.5" />
          <p className="text-xs text-brand-700 leading-relaxed">
            <strong>Browse & select</strong> the financial statement line items you want to analyze.
            Expand each section, check the items you need, then continue to Layer 2 to read
            related footnotes.
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="data-card p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search line items by name or XBRL concept..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 text-sm border border-gray-200 rounded-lg
                       focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500
                       placeholder:text-gray-400"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Selected items summary */}
      {selectedCount > 0 && (
        <div className="data-card p-3 bg-brand-50 border-brand-200">
          <div className="flex items-center justify-between">
            <p className="text-sm text-brand-700">
              <span className="font-bold">{selectedCount}</span> line item{selectedCount !== 1 ? 's' : ''} selected
            </p>
            <button
              onClick={onNextLayer}
              className="flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-white
                         bg-brand-600 rounded-lg hover:bg-brand-700 transition-colors"
            >
              Continue to Footnotes
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Grouped sections */}
      <div className="space-y-3">
        {STATEMENT_SECTIONS.map((section) => {
          const sectionItems = grouped[section.key] ?? []
          if (sectionItems.length === 0) return null

          const isCollapsed = collapsed.has(section.key)
          const Icon = section.icon
          const selectedInSection = sectionItems.filter((i) => selectedConcepts.has(i.concept)).length

          return (
            <div key={section.key} className="data-card overflow-hidden">
              {/* Section header */}
              <button
                onClick={() => toggleSection(section.key)}
                className="w-full flex items-center justify-between px-4 py-3 bg-gray-50
                           hover:bg-gray-100 transition-colors border-b border-gray-200"
              >
                <div className="flex items-center gap-2.5">
                  <ChevronDown
                    className={cn(
                      'w-4 h-4 text-gray-400 transition-transform',
                      isCollapsed && '-rotate-90',
                    )}
                  />
                  <Icon className="w-4 h-4 text-brand-500" />
                  <span className="text-sm font-semibold text-gray-800">{section.label}</span>
                  <span className="text-xs text-gray-400">({sectionItems.length})</span>
                </div>
                {selectedInSection > 0 && (
                  <span className="px-2 py-0.5 text-[10px] font-semibold text-brand-700 bg-brand-100 rounded-full">
                    {selectedInSection} selected
                  </span>
                )}
              </button>

              {/* Section items */}
              {!isCollapsed && (
                <div className="divide-y divide-gray-100">
                  {sectionItems.map((item) => {
                    const isSelected = selectedConcepts.has(item.concept)
                    return (
                      <div
                        key={item.concept}
                        onClick={() => onToggleConcept(item.concept)}
                        className={cn(
                          'flex items-center gap-3 px-4 py-2 cursor-pointer transition-colors',
                          isSelected ? 'bg-brand-50/60' : 'hover:bg-gray-50',
                        )}
                      >
                        <div
                          className={cn(
                            'w-5 h-5 rounded border-2 flex items-center justify-center transition-colors shrink-0',
                            isSelected
                              ? 'bg-brand-600 border-brand-600'
                              : 'border-gray-300',
                          )}
                        >
                          {isSelected && <Check className="w-3 h-3 text-white" />}
                        </div>

                        <div className="flex-1 min-w-0 flex items-center gap-4">
                          <span className="text-sm text-gray-900 font-medium whitespace-nowrap">
                            {item.label}
                          </span>
                          <code className="text-[11px] text-gray-400 font-mono whitespace-nowrap hidden lg:block">
                            {item.concept}
                          </code>
                        </div>

                        <div className="flex items-center gap-4 shrink-0">
                          <span className="text-xs font-mono text-gray-600 whitespace-nowrap">
                            {item.latest_value != null
                              ? item.unit === 'USD'
                                ? fmtNumber(item.latest_value)
                                : item.latest_value.toLocaleString()
                              : '—'}
                          </span>
                          <span className="text-[10px] text-gray-400 w-8 text-center">
                            {item.years_available}yr
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {filtered.length === 0 && (
        <div className="data-card py-12 text-center">
          <p className="text-sm text-gray-400">No line items match your search</p>
        </div>
      )}
    </div>
  )
}
