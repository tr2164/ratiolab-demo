'use client'

import { useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { BookOpen, ArrowLeft, Calculator, Sparkles } from 'lucide-react'
import CompanySearch from '@/components/CompanySearch'
import LayerNav, { LAYERS } from '@/components/ratiolab/LayerNav'
import AnalysisPanel from '@/components/ratiolab/AnalysisPanel'
import LearningObjective from '@/components/ratiolab/LearningObjective'
import Layer1LineItems from '@/components/ratiolab/layers/Layer1LineItems'
import Layer2Footnotes from '@/components/ratiolab/layers/Layer2Footnotes'
import Layer3RatioBuilder from '@/components/ratiolab/layers/Layer3RatioBuilder'
import Layer4Dashboard from '@/components/ratiolab/layers/Layer4Dashboard'
import {
  fetchLineItems, analyzeRatios,
  type LineItemCatalog, type RatioResultItem, type RatioAnalysisResult,
} from '@/services/api'

const LAYER_LABELS: Record<number, string> = {
  1: 'Browse Line Items',
  2: 'Read Footnotes',
  3: 'Build Ratios',
  4: 'Ratio Dashboard',
}

const LAYER_OBJECTIVES: Record<number, { title: string; body: React.ReactNode }> = {
  1: {
    title: 'Learning Objective',
    body: (
      <>
        <p>
          <strong>Explore the full set of financial data a company reports to the SEC.</strong> Every
          public company files structured XBRL data containing hundreds of line items across the
          balance sheet, income statement, and cash flow statement.
        </p>
        <p>
          Select the items you want to work with. The XBRL concept names (the codes) are the
          same standardized tags that analysts and regulators use to compare companies.
        </p>
      </>
    ),
  },
  2: {
    title: 'Learning Objective',
    body: (
      <>
        <p>
          <strong>Read the footnotes behind the numbers.</strong> Financial statements tell you
          &ldquo;what&rdquo; — the footnotes tell you &ldquo;how&rdquo; and &ldquo;why.&rdquo;
          Every significant accounting policy, estimate, and judgment is disclosed here.
        </p>
        <p>
          Footnotes are where you find depreciation methods, revenue recognition policies,
          allowance methodologies, and the assumptions behind fair value measurements.
        </p>
      </>
    ),
  },
  3: {
    title: 'Learning Objective',
    body: (
      <>
        <p>
          <strong>Build financial ratios from raw data.</strong> Ratios transform raw numbers into
          comparable metrics. A ratio is simply one line item divided by another, sometimes
          multiplied by a constant (×100 for percentages, ×365 for days).
        </p>
        <p>
          Try the templates first to see how standard ratios are constructed, then build your
          own. Multi-term ratios like Quick Ratio show how complex measures are assembled
          from individual components.
        </p>
      </>
    ),
  },
  4: {
    title: 'Learning Objective',
    body: (
      <>
        <p>
          <strong>Track ratios over time to find the story.</strong> A single ratio is a snapshot.
          A ratio over 5+ years reveals trends — improving profitability, deteriorating
          liquidity, increasing leverage. The trend matters more than any single value.
        </p>
        <p>
          Use the AI analysis to get an expert interpretation of what these trends mean
          and what questions they raise about the company&apos;s strategy and financial health.
        </p>
      </>
    ),
  },
}

export default function RatioLabPage() {
  const [catalog, setCatalog] = useState<LineItemCatalog | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [currentLayer, setCurrentLayer] = useState(1)
  const [ticker, setTicker] = useState('')
  const [selectedConcepts, setSelectedConcepts] = useState<Set<string>>(new Set())
  const [selectedLabels, setSelectedLabels] = useState<Record<string, string>>({})
  const [ratioResults, setRatioResults] = useState<RatioResultItem[]>([])

  const [analysis, setAnalysis] = useState<RatioAnalysisResult | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [analysisPanelOpen, setAnalysisPanelOpen] = useState(false)
  const fetchedAnalysis = useRef(false)
  const [activeFootnote, setActiveFootnote] = useState<{ name: string; text: string; concept: string } | null>(null)

  const enabledLayers = LAYERS.filter((l) => l.enabled).length

  const handleSearch = useCallback(async (t: string) => {
    setLoading(true)
    setError(null)
    setTicker(t)
    setSelectedConcepts(new Set())
    setSelectedLabels({})
    setRatioResults([])
    setAnalysis(null)
    fetchedAnalysis.current = false
    try {
      const result = await fetchLineItems(t)
      setCatalog(result)
      setCurrentLayer(1)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load data'
      setError(msg)
      setCatalog(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleToggleConcept = useCallback((concept: string) => {
    setSelectedConcepts((prev) => {
      const next = new Set(prev)
      if (next.has(concept)) next.delete(concept)
      else next.add(concept)
      return next
    })

    if (catalog) {
      const item = catalog.items.find((i) => i.concept === concept)
      if (item) {
        setSelectedLabels((prev) => ({ ...prev, [concept]: item.label }))
      }
    }
  }, [catalog])

  const triggerAnalysis = useCallback(() => {
    if (ratioResults.length === 0 || !ticker) return
    if (fetchedAnalysis.current) return
    fetchedAnalysis.current = true

    setAnalysisLoading(true)
    setAnalysisError(null)
    analyzeRatios(ticker, ratioResults)
      .then((result) => setAnalysis(result))
      .catch((err) => {
        fetchedAnalysis.current = false
        setAnalysisError(err instanceof Error ? err.message : 'Analysis failed')
      })
      .finally(() => setAnalysisLoading(false))
  }, [ratioResults, ticker])

  const handleOpenAnalysis = () => {
    if (!analysis && !analysisLoading) triggerAnalysis()
    setAnalysisPanelOpen(true)
  }

  const handleRatioResults = (results: RatioResultItem[]) => {
    setRatioResults(results)
    setAnalysis(null)
    fetchedAnalysis.current = false
  }

  const ratioContext = ratioResults.map((r) => {
    const vals = Object.entries(r.values)
      .filter(([, v]) => v != null)
      .map(([yr, v]) => `${yr}: ${Number(v).toFixed(2)}`)
      .join(', ')
    return `${r.name}: ${vals} (trend: ${r.trend})`
  }).join('\n')

  const disclosureContext = currentLayer === 2 && activeFootnote
    ? `${activeFootnote.name}\n${activeFootnote.text}`
    : ''

  const showAiButton = ratioResults.length > 0 || (currentLayer === 2 && !!activeFootnote)

  const objective = LAYER_OBJECTIVES[currentLayer]

  const [checkpointComplete, setCheckpointComplete] = useState(false)

  const handlePrevLayer = () => {
    if (currentLayer > 1) setCurrentLayer(currentLayer - 1)
  }
  const handleNextLayer = () => {
    const next = currentLayer + 1
    const nextData = LAYERS.find((l) => l.id === next)
    if (nextData?.enabled) setCurrentLayer(next)
  }

  const handleLayerChange = (layer: number) => {
    setCurrentLayer(layer)
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white sticky top-0 z-20">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Link
                href="/"
                className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-brand-600 transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                <BookOpen className="w-4 h-4" />
                <span>FinSight</span>
              </Link>
              <div className="h-5 w-px bg-gray-200" />
              <div className="flex items-center gap-2">
                <Calculator className="w-5 h-5 text-brand-500" />
                <h1 className="text-lg font-bold text-gray-900">Ratio Lab</h1>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <CompanySearch onSearch={handleSearch} loading={loading} />
              {showAiButton && (
                <button
                  onClick={handleOpenAnalysis}
                  className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium rounded-lg
                             border transition-colors ${
                    analysis
                      ? 'text-amber-700 bg-amber-50 border-amber-200 hover:bg-amber-100'
                      : analysisLoading
                        ? 'text-amber-500 bg-amber-50/50 border-amber-200 cursor-wait'
                        : 'text-brand-600 bg-brand-50 border-brand-200 hover:bg-brand-100'
                  }`}
                >
                  {analysisLoading ? (
                    <div className="w-3.5 h-3.5 border-2 border-amber-200 border-t-amber-500 rounded-full animate-spin" />
                  ) : (
                    <Sparkles className="w-3.5 h-3.5" />
                  )}
                  <span className="hidden sm:inline">
                    {currentLayer === 2
                      ? 'Explain Disclosure'
                      : analysis ? 'AI Analysis' : analysisLoading ? 'Analyzing...' : 'Run AI Analysis'}
                  </span>
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {catalog && (
          <LayerNav
            current={currentLayer}
            onChange={handleLayerChange}
            hasData={!!catalog}
          />
        )}

        {catalog && !loading && (
          <div className="data-card p-4 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3">
                <span className="text-xl font-bold text-gray-900">{catalog.company.ticker}</span>
                <span className="text-gray-500">{catalog.company.name}</span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">
                CIK {catalog.company.cik} &middot; {catalog.items.length} line items available
              </p>
            </div>
            {selectedConcepts.size > 0 && (
              <span className="px-2.5 py-1 text-xs font-semibold text-brand-700 bg-brand-50 rounded-full">
                {selectedConcepts.size} selected
              </span>
            )}
          </div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-500 mb-4" />
            <p className="text-gray-500 text-sm">
              Loading financial statement data for <span className="font-mono font-bold">{ticker}</span>...
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Fetching all reported line items from SEC Company Facts API
            </p>
          </div>
        )}

        {error && (
          <div className="data-card p-6 border-l-4 border-red-400">
            <p className="font-semibold text-red-700 mb-1">Failed to load data</p>
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

        {!catalog && !loading && !error && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Calculator className="w-16 h-16 text-gray-200 mb-4" />
            <h2 className="text-xl font-bold text-gray-400 mb-2">Enter a Ticker to Begin</h2>
            <p className="text-gray-400 text-sm max-w-md">
              Type any public company ticker (e.g., AAPL, MSFT, JNJ) to browse their full set
              of financial statement line items and build custom ratios from SEC EDGAR data.
            </p>
          </div>
        )}

        {catalog && !loading && (
          <>
            {currentLayer === 1 && (
              <Layer1LineItems
                items={catalog.items}
                categoryCounts={catalog.category_counts}
                selectedConcepts={selectedConcepts}
                onToggleConcept={handleToggleConcept}
                onNextLayer={() => setCurrentLayer(2)}
              />
            )}
            {currentLayer === 2 && (
              <Layer2Footnotes
                ticker={ticker}
                selectedConcepts={selectedConcepts}
                onPrevLayer={() => setCurrentLayer(1)}
                onNextLayer={() => setCurrentLayer(3)}
                onOpenAnalysis={handleOpenAnalysis}
                analysisReady={!!analysis}
                analysisLoading={analysisLoading}
                onActiveFootnoteChange={setActiveFootnote}
              />
            )}
            {currentLayer === 3 && (
              <Layer3RatioBuilder
                ticker={ticker}
                selectedConcepts={selectedConcepts}
                selectedLabels={selectedLabels}
                ratioResults={ratioResults}
                onRatioResults={handleRatioResults}
                onPrevLayer={() => setCurrentLayer(2)}
                onNextLayer={() => setCurrentLayer(4)}
              />
            )}
            {currentLayer === 4 && (
              <Layer4Dashboard
                ratioResults={ratioResults}
                companyName={catalog.company.name}
                onPrevLayer={() => setCurrentLayer(3)}
                onOpenAnalysis={handleOpenAnalysis}
                analysisReady={!!analysis}
                analysisLoading={analysisLoading}
              />
            )}
          </>
        )}
      </main>

      <AnalysisPanel
        open={analysisPanelOpen}
        onClose={() => setAnalysisPanelOpen(false)}
        analysis={analysis}
        loading={analysisLoading}
        error={analysisError}
        companyName={catalog?.company.name ?? ticker}
        ticker={ticker}
        layerLabel={LAYER_LABELS[currentLayer] ?? `Layer ${currentLayer}`}
        ratioContext={ratioContext}
        disclosureContext={disclosureContext}
        onRetry={triggerAnalysis}
      />

      {catalog && objective && (
        <LearningObjective
          currentLayer={currentLayer}
          totalLayers={enabledLayers}
          title={objective.title}
          onPrevLayer={handlePrevLayer}
          onNextLayer={handleNextLayer}
          onCheckpointComplete={setCheckpointComplete}
        >
          {objective.body}
        </LearningObjective>
      )}
    </div>
  )
}
