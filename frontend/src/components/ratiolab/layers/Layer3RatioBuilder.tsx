'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  ChevronLeft, ChevronRight, Plus, Minus, X, Calculator, Zap, Check,
  AlertTriangle, Loader2, Info,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  computeRatios, fetchRatioTemplates,
  type RatioDefinition, type RatioTerm, type RatioResultItem, type RatioTemplate,
} from '@/services/api'

const MULTIPLIER_OPTIONS = [
  { value: 1, label: '×1 (ratio)', display: '' },
  { value: 100, label: '×100 (%)', display: '%' },
  { value: 365, label: '×365 (days)', display: ' days' },
]

const TEMPLATE_CATEGORIES = ['Liquidity', 'Profitability', 'Leverage', 'Efficiency']

interface Layer3RatioBuilderProps {
  ticker: string
  selectedConcepts: Set<string>
  selectedLabels: Record<string, string>
  ratioResults: RatioResultItem[]
  onRatioResults: (results: RatioResultItem[]) => void
  onPrevLayer: () => void
  onNextLayer: () => void
}

export default function Layer3RatioBuilder({
  ticker, selectedConcepts, selectedLabels, ratioResults, onRatioResults,
  onPrevLayer, onNextLayer,
}: Layer3RatioBuilderProps) {
  const [ratioName, setRatioName] = useState('')
  const [numeratorTerms, setNumeratorTerms] = useState<RatioTerm[]>([{ concept: '', sign: '+' }])
  const [denominatorTerms, setDenominatorTerms] = useState<RatioTerm[]>([{ concept: '', sign: '+' }])
  const [multiplyBy, setMultiplyBy] = useState(1)
  const [computing, setComputing] = useState(false)
  const [templates, setTemplates] = useState<RatioTemplate[]>([])
  const [templateCategory, setTemplateCategory] = useState('Liquidity')
  const [showTemplates, setShowTemplates] = useState(true)

  useEffect(() => {
    fetchRatioTemplates(ticker).then(setTemplates).catch(() => {})
  }, [ticker])

  const allConceptOptions = Array.from(selectedConcepts).map((c) => ({
    value: c,
    label: selectedLabels[c] || c.split(':').pop() || c,
  }))

  const handleAddTerm = (side: 'num' | 'den') => {
    const newTerm: RatioTerm = { concept: '', sign: '+' }
    if (side === 'num') setNumeratorTerms((prev) => [...prev, newTerm])
    else setDenominatorTerms((prev) => [...prev, newTerm])
  }

  const handleRemoveTerm = (side: 'num' | 'den', idx: number) => {
    if (side === 'num') setNumeratorTerms((prev) => prev.filter((_, i) => i !== idx))
    else setDenominatorTerms((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleUpdateTerm = (side: 'num' | 'den', idx: number, field: 'concept' | 'sign', value: string) => {
    const setter = side === 'num' ? setNumeratorTerms : setDenominatorTerms
    setter((prev) => prev.map((t, i) => (i === idx ? { ...t, [field]: value } : t)))
  }

  const canCompute = ratioName.trim() &&
    numeratorTerms.some((t) => t.concept) &&
    denominatorTerms.some((t) => t.concept)

  const handleCompute = useCallback(async () => {
    if (!canCompute) return
    setComputing(true)

    const definition: RatioDefinition = {
      name: ratioName.trim(),
      numerator_terms: numeratorTerms.filter((t) => t.concept),
      denominator_terms: denominatorTerms.filter((t) => t.concept),
      multiply_by: multiplyBy,
    }

    try {
      const allDefs = [...ratioResults.map((r) => r.definition), definition]
      const response = await computeRatios(ticker, allDefs)
      onRatioResults(response.results)
      setRatioName('')
      setNumeratorTerms([{ concept: '', sign: '+' }])
      setDenominatorTerms([{ concept: '', sign: '+' }])
      setMultiplyBy(1)
    } catch {
      // keep current state
    } finally {
      setComputing(false)
    }
  }, [canCompute, ratioName, numeratorTerms, denominatorTerms, multiplyBy, ticker, ratioResults, onRatioResults])

  const handleApplyTemplate = useCallback(async (template: RatioTemplate) => {
    setComputing(true)
    const definition: RatioDefinition = {
      name: template.name,
      numerator_terms: template.numerator_terms,
      denominator_terms: template.denominator_terms,
      multiply_by: template.multiply_by,
    }

    try {
      const allDefs = [...ratioResults.map((r) => r.definition), definition]
      const response = await computeRatios(ticker, allDefs)
      onRatioResults(response.results)
    } catch {
      // keep current state
    } finally {
      setComputing(false)
    }
  }, [ticker, ratioResults, onRatioResults])

  const handleRemoveRatio = (idx: number) => {
    onRatioResults(ratioResults.filter((_, i) => i !== idx))
  }

  const filteredTemplates = templates.filter((t) => t.category === templateCategory)
  const existingNames = new Set(ratioResults.map((r) => r.name))

  const multiplierDisplay = MULTIPLIER_OPTIONS.find((o) => o.value === multiplyBy)?.display ?? ''

  return (
    <div className="space-y-4">
      {/* Coaching bar */}
      {selectedConcepts.size === 0 && (
        <div className="coaching-panel">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-brand-500 shrink-0 mt-0.5" />
            <p className="text-xs text-brand-700 leading-relaxed">
              <strong>Tip:</strong> You can use ratio templates without selecting line items first.
              Templates use standardized XBRL concepts and pull data directly from the SEC.
              For custom ratios, go back to Layer 1 and select the specific line items you want to use.
            </p>
          </div>
        </div>
      )}

      {/* Templates section */}
      <div className="data-card overflow-hidden">
        <button
          onClick={() => setShowTemplates((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-500" />
            <span className="text-sm font-semibold text-gray-800">Ratio Templates</span>
            <span className="text-xs text-gray-400">One-click common ratios</span>
          </div>
          <ChevronRight className={cn('w-4 h-4 text-gray-400 transition-transform', showTemplates && 'rotate-90')} />
        </button>

        {showTemplates && (
          <div className="p-4 space-y-3">
            <div className="flex items-center gap-1">
              {TEMPLATE_CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setTemplateCategory(cat)}
                  className={cn(
                    'px-3 py-1 text-xs font-medium rounded-lg transition-colors',
                    templateCategory === cat
                      ? 'bg-brand-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200',
                  )}
                >
                  {cat}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {filteredTemplates.map((template) => {
                const alreadyAdded = existingNames.has(template.name)
                const isAvailable = template.available !== false

                return (
                  <button
                    key={template.name}
                    onClick={() => !alreadyAdded && isAvailable && handleApplyTemplate(template)}
                    disabled={alreadyAdded || !isAvailable || computing}
                    className={cn(
                      'flex items-center gap-2 px-3 py-2.5 rounded-lg border text-left transition-colors text-xs',
                      alreadyAdded
                        ? 'bg-green-50 border-green-200 text-green-700 cursor-default'
                        : isAvailable
                          ? 'bg-white border-gray-200 text-gray-700 hover:border-brand-300 hover:bg-brand-50'
                          : 'bg-gray-50 border-gray-200 text-gray-400 cursor-not-allowed',
                    )}
                  >
                    {alreadyAdded ? (
                      <Check className="w-3.5 h-3.5 text-green-500 shrink-0" />
                    ) : !isAvailable ? (
                      <AlertTriangle className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                    ) : (
                      <Plus className="w-3.5 h-3.5 text-brand-400 shrink-0" />
                    )}
                    <span className="font-medium truncate">{template.name}</span>
                  </button>
                )
              })}
            </div>

            {filteredTemplates.length === 0 && (
              <p className="text-xs text-gray-400 text-center py-2">No templates in this category</p>
            )}
          </div>
        )}
      </div>

      {/* Custom ratio builder */}
      <div className="data-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Calculator className="w-4 h-4 text-brand-500" />
          <h3 className="text-sm font-semibold text-gray-800">Custom Ratio Builder</h3>
        </div>

        {/* Ratio name */}
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Ratio Name</label>
          <input
            type="text"
            value={ratioName}
            onChange={(e) => setRatioName(e.target.value)}
            placeholder="e.g., Working Capital Ratio"
            className="mt-1 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg
                       focus:outline-none focus:ring-2 focus:ring-brand-500 placeholder:text-gray-400"
          />
        </div>

        {/* Numerator */}
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Numerator</label>
          <div className="mt-1 space-y-2">
            {numeratorTerms.map((term, idx) => (
              <TermRow
                key={idx}
                term={term}
                options={allConceptOptions}
                onUpdate={(field, value) => handleUpdateTerm('num', idx, field, value)}
                onRemove={numeratorTerms.length > 1 ? () => handleRemoveTerm('num', idx) : undefined}
                showSign={idx > 0}
              />
            ))}
            <button
              onClick={() => handleAddTerm('num')}
              className="flex items-center gap-1 text-xs text-brand-600 hover:text-brand-700 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Add term
            </button>
          </div>
        </div>

        {/* Divider line */}
        <div className="flex items-center gap-3">
          <div className="flex-1 h-px bg-gray-300" />
          <span className="text-xs font-bold text-gray-400">÷</span>
          <div className="flex-1 h-px bg-gray-300" />
        </div>

        {/* Denominator */}
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Denominator</label>
          <div className="mt-1 space-y-2">
            {denominatorTerms.map((term, idx) => (
              <TermRow
                key={idx}
                term={term}
                options={allConceptOptions}
                onUpdate={(field, value) => handleUpdateTerm('den', idx, field, value)}
                onRemove={denominatorTerms.length > 1 ? () => handleRemoveTerm('den', idx) : undefined}
                showSign={idx > 0}
              />
            ))}
            <button
              onClick={() => handleAddTerm('den')}
              className="flex items-center gap-1 text-xs text-brand-600 hover:text-brand-700 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Add term
            </button>
          </div>
        </div>

        {/* Multiplier */}
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Display As</label>
          <div className="mt-1 flex items-center gap-2">
            {MULTIPLIER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setMultiplyBy(opt.value)}
                className={cn(
                  'px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors',
                  multiplyBy === opt.value
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-brand-300',
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Add ratio button */}
        <button
          onClick={handleCompute}
          disabled={!canCompute || computing}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium
                     text-white bg-brand-600 rounded-lg hover:bg-brand-700
                     disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {computing ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Computing...
            </>
          ) : (
            <>
              <Plus className="w-4 h-4" />
              Add Ratio
            </>
          )}
        </button>
      </div>

      {/* Computed ratios preview */}
      {ratioResults.length > 0 && (
        <div className="data-card overflow-hidden">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-800">
              Computed Ratios ({ratioResults.length})
            </h3>
          </div>
          <div className="divide-y divide-gray-100">
            {ratioResults.map((result, idx) => {
              const years = Object.entries(result.values)
                .filter(([, v]) => v != null)
                .sort(([a], [b]) => Number(a) - Number(b))

              const display = MULTIPLIER_OPTIONS.find(
                (o) => o.value === result.definition.multiply_by
              )?.display ?? ''

              return (
                <div key={idx} className="px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-gray-800">{result.name}</span>
                      {result.trend && (
                        <span className={cn(
                          'text-[10px] font-semibold px-1.5 py-0.5 rounded',
                          result.trend === 'up' && 'bg-green-100 text-green-700',
                          result.trend === 'down' && 'bg-red-100 text-red-700',
                          result.trend === 'stable' && 'bg-gray-100 text-gray-600',
                        )}>
                          {result.trend === 'up' ? '▲ Up' : result.trend === 'down' ? '▼ Down' : '● Stable'}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => handleRemoveRatio(idx)}
                      className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="flex items-center gap-3 overflow-x-auto">
                    {years.map(([yr, val]) => (
                      <div key={yr} className="text-center shrink-0">
                        <p className="text-[10px] text-gray-400">{yr}</p>
                        <p className="text-xs font-mono font-medium text-gray-700">
                          {val != null ? `${Number(val).toFixed(2)}${display}` : '—'}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={onPrevLayer}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-brand-600 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Footnotes
        </button>
        {ratioResults.length > 0 && (
          <button
            onClick={onNextLayer}
            className="flex items-center gap-1 px-4 py-2 text-sm font-medium text-white
                       bg-brand-600 rounded-lg hover:bg-brand-700 transition-colors"
          >
            Continue to Dashboard
            <ChevronRight className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  )
}


function TermRow({
  term, options, onUpdate, onRemove, showSign,
}: {
  term: RatioTerm
  options: { value: string; label: string }[]
  onUpdate: (field: 'concept' | 'sign', value: string) => void
  onRemove?: () => void
  showSign: boolean
}) {
  return (
    <div className="flex items-center gap-2">
      {showSign && (
        <button
          onClick={() => onUpdate('sign', term.sign === '+' ? '-' : '+')}
          className={cn(
            'w-7 h-7 flex items-center justify-center rounded border text-xs font-bold transition-colors',
            term.sign === '+'
              ? 'border-green-300 text-green-600 bg-green-50'
              : 'border-red-300 text-red-600 bg-red-50',
          )}
        >
          {term.sign === '+' ? <Plus className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
        </button>
      )}
      {!showSign && <div className="w-7" />}

      <select
        value={term.concept}
        onChange={(e) => onUpdate('concept', e.target.value)}
        className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white
                   focus:outline-none focus:ring-2 focus:ring-brand-500"
      >
        <option value="">Select a line item...</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {onRemove && (
        <button
          onClick={onRemove}
          className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  )
}
