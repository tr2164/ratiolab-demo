'use client'

import { useState, useEffect, useMemo } from 'react'
import {
  ChevronLeft, ChevronRight, FileText, Loader2, AlertCircle, Sparkles,
  Search, X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { fetchStatementFootnotes, type FootnoteBlock } from '@/services/api'

function cleanConceptName(raw: string): string {
  let name = raw.split(':').pop() ?? raw
  name = name
    .replace(/TextBlock$/i, '')
    .replace(/TableTextBlock$/i, '')
    .replace(/PolicyTextBlock$/i, ' Policy')
    .replace(/DisclosureTextBlock$/i, '')
  return name.replace(/([a-z])([A-Z])/g, '$1 $2').trim()
}

function estimateReadingLength(text: string): string {
  const words = text.split(/\s+/).length
  if (words > 1000) return 'Long'
  if (words > 300) return 'Medium'
  return 'Short'
}

interface Layer2FootnotesProps {
  ticker: string
  selectedConcepts: Set<string>
  onPrevLayer: () => void
  onNextLayer: () => void
  onOpenAnalysis: () => void
  analysisReady: boolean
  analysisLoading: boolean
  onActiveFootnoteChange?: (footnote: { name: string; text: string; concept: string } | null) => void
}

export default function Layer2Footnotes({
  ticker, selectedConcepts, onPrevLayer, onNextLayer, onOpenAnalysis, analysisLoading,
  onActiveFootnoteChange,
}: Layer2FootnotesProps) {
  const [blocks, setBlocks] = useState<FootnoteBlock[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeIdx, setActiveIdx] = useState(0)
  const [viewMode, setViewMode] = useState<'html' | 'text'>('html')
  const [listSearch, setListSearch] = useState('')

  useEffect(() => {
    if (selectedConcepts.size === 0) return
    setLoading(true)
    setError(null)
    fetchStatementFootnotes(ticker, Array.from(selectedConcepts))
      .then((res) => {
        setBlocks(res.blocks)
        setActiveIdx(0)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load footnotes'))
      .finally(() => setLoading(false))
  }, [ticker, selectedConcepts])

  const enrichedBlocks = useMemo(() =>
    blocks.map((b, i) => ({
      ...b,
      idx: i,
      displayName: cleanConceptName(b.xbrl_concept),
      length: estimateReadingLength(b.text),
    })),
    [blocks],
  )

  const filteredList = useMemo(() => {
    if (!listSearch) return enrichedBlocks
    const q = listSearch.toLowerCase()
    return enrichedBlocks.filter(
      (b) => b.displayName.toLowerCase().includes(q) || b.xbrl_concept.toLowerCase().includes(q)
    )
  }, [enrichedBlocks, listSearch])

  useEffect(() => {
    if (!onActiveFootnoteChange) return
    const current = enrichedBlocks[activeIdx]
    if (current) {
      onActiveFootnoteChange({
        name: current.displayName,
        text: current.text,
        concept: current.xbrl_concept,
      })
    } else {
      onActiveFootnoteChange(null)
    }
  }, [activeIdx, enrichedBlocks, onActiveFootnoteChange])

  if (selectedConcepts.size === 0) {
    return (
      <div className="data-card p-8 text-center">
        <FileText className="w-12 h-12 text-gray-200 mx-auto mb-3" />
        <p className="text-sm text-gray-500">No line items selected</p>
        <p className="text-xs text-gray-400 mt-1">Go back to Layer 1 and select items to see related footnotes</p>
        <button
          onClick={onPrevLayer}
          className="mt-4 flex items-center gap-1 mx-auto text-sm text-brand-600 hover:text-brand-700"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Line Items
        </button>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Loader2 className="w-8 h-8 text-brand-500 animate-spin mb-3" />
        <p className="text-sm text-gray-500">Searching XBRL filing for related disclosures...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="data-card p-6 border-l-4 border-red-400">
        <div className="flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-red-700 mb-1">Failed to load footnotes</p>
            <p className="text-sm text-red-600">{error}</p>
          </div>
        </div>
      </div>
    )
  }

  if (blocks.length === 0) {
    return (
      <div className="space-y-4">
        <div className="data-card p-8 text-center">
          <FileText className="w-12 h-12 text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-gray-500">No footnotes found for the selected items</p>
          <p className="text-xs text-gray-400 mt-1">
            Not all line items have related text disclosures in the XBRL filing
          </p>
        </div>
        <NavButtons onPrevLayer={onPrevLayer} onNextLayer={onNextLayer} />
      </div>
    )
  }

  const currentBlock = enrichedBlocks[activeIdx]

  return (
    <div className="space-y-4">
      {/* AI coaching bar — top position */}
      <div className="coaching-panel">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles className="w-4 h-4 text-amber-500 shrink-0" />
            <p className="text-sm text-brand-800 truncate">
              {currentBlock
                ? <>AI can explain <strong>&ldquo;{currentBlock.displayName}&rdquo;</strong> for you</>
                : 'Select a disclosure to get an AI explanation'}
            </p>
          </div>
          <button
            onClick={onOpenAnalysis}
            disabled={analysisLoading}
            className="px-3 py-1.5 text-xs font-medium text-white bg-brand-600 rounded-lg
                       hover:bg-brand-700 disabled:opacity-50 transition-colors shrink-0 ml-3"
          >
            {analysisLoading ? 'Analyzing...' : 'Explain Disclosure'}
          </button>
        </div>
      </div>

      {/* Master-detail layout */}
      <div className="data-card overflow-hidden flex" style={{ minHeight: 520 }}>
        {/* Sidebar list */}
        <div className="w-72 shrink-0 border-r border-gray-200 flex flex-col bg-gray-50/50">
          <div className="px-3 py-2.5 border-b border-gray-200 bg-gray-50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Disclosures
              </span>
              <span className="text-[10px] text-gray-400">{blocks.length} found</span>
            </div>
            {blocks.length > 5 && (
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Filter..."
                  value={listSearch}
                  onChange={(e) => setListSearch(e.target.value)}
                  className="w-full pl-7 pr-6 py-1.5 text-xs border border-gray-200 rounded-md
                             focus:outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-gray-400"
                />
                {listSearch && (
                  <button
                    onClick={() => setListSearch('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto">
            {filteredList.map((block) => (
              <button
                key={block.idx}
                onClick={() => setActiveIdx(block.idx)}
                className={cn(
                  'w-full text-left px-3 py-2.5 border-b border-gray-100 transition-colors',
                  activeIdx === block.idx
                    ? 'bg-brand-50 border-l-2 border-l-brand-500'
                    : 'hover:bg-gray-100 border-l-2 border-l-transparent',
                )}
              >
                <p className={cn(
                  'text-xs font-medium leading-snug',
                  activeIdx === block.idx ? 'text-brand-700' : 'text-gray-700',
                )}>
                  {block.displayName}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  {block.fiscal_year && (
                    <span className="text-[10px] text-gray-400">FY {block.fiscal_year}</span>
                  )}
                  <span className={cn(
                    'text-[10px] px-1.5 py-0.5 rounded',
                    block.length === 'Long' ? 'bg-amber-100 text-amber-600' :
                    block.length === 'Medium' ? 'bg-blue-100 text-blue-600' :
                    'bg-gray-100 text-gray-500',
                  )}>
                    {block.length}
                  </span>
                </div>
              </button>
            ))}

            {filteredList.length === 0 && (
              <div className="px-3 py-6 text-center">
                <p className="text-xs text-gray-400">No matches</p>
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {currentBlock && (
            <>
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 bg-white shrink-0">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-800 truncate">
                    {currentBlock.displayName}
                  </p>
                  <code className="text-[10px] text-gray-400 font-mono">{currentBlock.xbrl_concept}</code>
                </div>
                <div className="flex items-center gap-1 shrink-0 ml-3">
                  <button
                    onClick={() => setViewMode('html')}
                    className={cn(
                      'px-2.5 py-1 text-[11px] font-medium rounded transition-colors',
                      viewMode === 'html'
                        ? 'bg-brand-100 text-brand-700'
                        : 'text-gray-500 hover:bg-gray-100',
                    )}
                  >
                    Rendered
                  </button>
                  <button
                    onClick={() => setViewMode('text')}
                    className={cn(
                      'px-2.5 py-1 text-[11px] font-medium rounded transition-colors',
                      viewMode === 'text'
                        ? 'bg-brand-100 text-brand-700'
                        : 'text-gray-500 hover:bg-gray-100',
                    )}
                  >
                    Plain Text
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-4">
                {viewMode === 'html' ? (
                  <div
                    className="prose prose-sm max-w-none text-gray-700
                               [&_table]:text-xs [&_table]:border-collapse
                               [&_td]:border [&_td]:border-gray-200 [&_td]:px-2 [&_td]:py-1
                               [&_th]:border [&_th]:border-gray-200 [&_th]:px-2 [&_th]:py-1 [&_th]:bg-gray-50"
                    dangerouslySetInnerHTML={{ __html: currentBlock.html }}
                  />
                ) : (
                  <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono leading-relaxed">
                    {currentBlock.text}
                  </pre>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <NavButtons onPrevLayer={onPrevLayer} onNextLayer={onNextLayer} />
    </div>
  )
}


function NavButtons({ onPrevLayer, onNextLayer }: { onPrevLayer: () => void; onNextLayer: () => void }) {
  return (
    <div className="flex items-center justify-between">
      <button
        onClick={onPrevLayer}
        className="flex items-center gap-1 text-sm text-gray-500 hover:text-brand-600 transition-colors"
      >
        <ChevronLeft className="w-4 h-4" />
        Back to Line Items
      </button>
      <button
        onClick={onNextLayer}
        className="flex items-center gap-1 px-4 py-2 text-sm font-medium text-white
                   bg-brand-600 rounded-lg hover:bg-brand-700 transition-colors"
      >
        Continue to Ratio Builder
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  )
}
