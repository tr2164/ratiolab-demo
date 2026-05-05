'use client'

import { useState, useMemo } from 'react'
import { ChevronLeft, TrendingUp, TrendingDown, Minus, Sparkles, BarChart3, AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RatioResultItem } from '@/services/api'
import {
  ResponsiveContainer, AreaChart, Area, LineChart, Line,
  XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid,
} from 'recharts'

interface Layer4DashboardProps {
  ratioResults: RatioResultItem[]
  companyName: string
  onPrevLayer: () => void
  onOpenAnalysis: () => void
  analysisReady: boolean
  analysisLoading: boolean
}

const MULTIPLIER_LABELS: Record<number, string> = {
  1: '',
  100: '%',
  365: ' days',
}

const CHART_COLORS = [
  '#6366f1', '#f59e0b', '#10b981', '#ef4444',
  '#8b5cf6', '#06b6d4', '#f97316', '#ec4899',
]

interface RatioGuide {
  what: string
  benchmark: string
  higher: string
  lower: string
  refLine?: number
  refLabel?: string
  assess: (val: number) => 'good' | 'caution' | 'concern'
}

const RATIO_GUIDES: Record<string, RatioGuide> = {
  'Current Ratio': {
    what: 'Measures whether the company can pay its short-term obligations with short-term assets.',
    benchmark: 'Healthy: 1.5–3.0. Below 1.0 means current liabilities exceed current assets.',
    higher: 'More short-term cushion, but very high values may signal idle assets.',
    lower: 'Less liquidity buffer. Below 1.0 is a warning sign — the company may struggle to pay near-term bills.',
    refLine: 1.0, refLabel: 'Break-even (1.0)',
    assess: (v) => v >= 1.5 ? 'good' : v >= 1.0 ? 'caution' : 'concern',
  },
  'Quick Ratio': {
    what: 'Like the Current Ratio but excludes inventory — a stricter test of immediate liquidity.',
    benchmark: 'Healthy: above 1.0. Below 0.5 is a red flag.',
    higher: 'Strong ability to meet obligations without selling inventory.',
    lower: 'May need to sell inventory or borrow to cover short-term debts.',
    refLine: 1.0, refLabel: 'Target (1.0)',
    assess: (v) => v >= 1.0 ? 'good' : v >= 0.5 ? 'caution' : 'concern',
  },
  'Cash Ratio': {
    what: 'The most conservative liquidity test — only cash and equivalents vs. current liabilities.',
    benchmark: 'Healthy: 0.5–1.0. Very few companies maintain ratios above 1.0.',
    higher: 'Excellent cash position, though excess cash can indicate underinvestment.',
    lower: 'Company relies on receivables or credit to meet obligations — common but worth monitoring.',
    refLine: 0.5, refLabel: 'Healthy floor (0.5)',
    assess: (v) => v >= 0.5 ? 'good' : v >= 0.2 ? 'caution' : 'concern',
  },
  'Debt to Equity': {
    what: 'How much debt the company uses relative to shareholder equity — its leverage level.',
    benchmark: 'Varies by industry. Below 1.0 is conservative, above 2.0 is highly leveraged.',
    higher: 'More financial risk — more of the business is funded by debt than by owners.',
    lower: 'More conservatively financed, but may be underutilizing leverage for growth.',
    refLine: 1.0, refLabel: 'Conservative cap (1.0)',
    assess: (v) => v <= 1.0 ? 'good' : v <= 2.0 ? 'caution' : 'concern',
  },
  'Debt to Assets': {
    what: 'What percentage of total assets are financed by debt.',
    benchmark: 'Below 50% is generally conservative. Above 70% signals high leverage.',
    higher: 'Greater portion of assets funded by creditors — higher financial risk.',
    lower: 'More equity-funded — lower risk but potentially lower returns to shareholders.',
    refLine: 50, refLabel: '50% threshold',
    assess: (v) => v <= 50 ? 'good' : v <= 70 ? 'caution' : 'concern',
  },
  'Equity Multiplier': {
    what: 'Total assets per dollar of equity — another way to measure leverage.',
    benchmark: 'A value of 2.0 means half the assets are debt-financed. Higher = more leveraged.',
    higher: 'More leverage amplifies both gains and losses for equity holders.',
    lower: 'Less leverage — more conservative capital structure.',
    refLine: 2.0, refLabel: '50% leverage (2.0)',
    assess: (v) => v <= 2.0 ? 'good' : v <= 3.0 ? 'caution' : 'concern',
  },
  'Interest Coverage': {
    what: 'How many times operating income covers interest expense — can the company afford its debt?',
    benchmark: 'Healthy: above 3.0. Below 1.5 is a warning sign.',
    higher: 'Comfortably covering debt costs with plenty of margin.',
    lower: 'Earnings barely cover interest — vulnerable to a downturn.',
    refLine: 3.0, refLabel: 'Healthy floor (3.0)',
    assess: (v) => v >= 3.0 ? 'good' : v >= 1.5 ? 'caution' : 'concern',
  },
  'Gross Margin': {
    what: 'Revenue kept after cost of goods sold — how much the core product/service earns.',
    benchmark: 'Varies widely: Software 70–90%, Retail 20–40%, Manufacturing 25–45%.',
    higher: 'Strong pricing power or low production costs — a competitive advantage.',
    lower: 'Thin margins from competitive pressure or high input costs.',
    assess: (v) => v >= 40 ? 'good' : v >= 20 ? 'caution' : 'concern',
  },
  'Operating Margin': {
    what: 'Revenue kept after all operating expenses — how efficiently the company runs.',
    benchmark: 'Healthy: 15%+ for most industries. Tech often 20–30%+.',
    higher: 'Efficient operations — good cost control relative to revenue.',
    lower: 'High operating costs eating into revenue. May need cost restructuring.',
    refLine: 15, refLabel: 'Healthy floor (15%)',
    assess: (v) => v >= 15 ? 'good' : v >= 5 ? 'caution' : 'concern',
  },
  'Net Margin': {
    what: 'Bottom-line profit as a percentage of revenue — what shareholders ultimately earn.',
    benchmark: 'Healthy: 10%+. Below 5% is thin. Negative means losses.',
    higher: 'Strong profitability after all expenses, taxes, and interest.',
    lower: 'Slim profits or losses — check what is consuming revenue.',
    refLine: 10, refLabel: 'Healthy floor (10%)',
    assess: (v) => v >= 10 ? 'good' : v >= 2 ? 'caution' : 'concern',
  },
  'Return on Assets': {
    what: 'How effectively the company uses its assets to generate profit.',
    benchmark: 'Varies: Asset-light businesses 15%+, capital-intensive 5–10%.',
    higher: 'Efficient use of capital — generating strong returns from the asset base.',
    lower: 'Assets are not producing much profit — possible overinvestment or low margins.',
    assess: (v) => v >= 8 ? 'good' : v >= 3 ? 'caution' : 'concern',
  },
  'Return on Equity': {
    what: 'Profit generated per dollar of shareholder equity — the return to owners.',
    benchmark: 'Healthy: 15–25%. Above 30% can indicate high leverage.',
    higher: 'Strong returns for shareholders, but verify it is not leverage-driven.',
    lower: 'Equity is not working hard — low profitability or excess equity.',
    refLine: 15, refLabel: 'Healthy floor (15%)',
    assess: (v) => v >= 15 ? 'good' : v >= 8 ? 'caution' : 'concern',
  },
  'Asset Turnover': {
    what: 'Revenue generated per dollar of assets — how hard assets work.',
    benchmark: 'Retail: 2.0+, Manufacturing: 0.5–1.5, Tech: 0.3–0.8.',
    higher: 'Assets are generating revenue efficiently.',
    lower: 'May have underutilized or overvalued assets.',
    assess: (v) => v >= 0.8 ? 'good' : v >= 0.3 ? 'caution' : 'concern',
  },
  'Inventory Turnover': {
    what: 'How many times inventory is sold and replaced per year.',
    benchmark: 'Higher is generally better. Grocery: 12+, Retail: 4–8, Manufacturing: 3–6.',
    higher: 'Fast-moving inventory — efficient supply chain and demand.',
    lower: 'Slow-moving inventory — risk of obsolescence or overstock.',
    assess: (v) => v >= 6 ? 'good' : v >= 3 ? 'caution' : 'concern',
  },
  'Receivables Turnover': {
    what: 'How many times receivables are collected per year — speed of cash collection.',
    benchmark: 'Higher is better. 10+ is fast, below 5 may indicate collection issues.',
    higher: 'Customers pay quickly — healthy cash conversion.',
    lower: 'Slow collections — potential credit risk or weak payment terms.',
    assess: (v) => v >= 8 ? 'good' : v >= 4 ? 'caution' : 'concern',
  },
  'Days Sales Outstanding': {
    what: 'Average days to collect payment from customers after a sale.',
    benchmark: 'Lower is better. 30–45 days is typical. Above 60 may signal problems.',
    higher: 'Slow collections — cash is tied up in receivables longer.',
    lower: 'Fast collections — cash flow advantage.',
    refLine: 45, refLabel: 'Typical max (45d)',
    assess: (v) => v <= 45 ? 'good' : v <= 60 ? 'caution' : 'concern',
  },
  'Days Inventory Outstanding': {
    what: 'Average days inventory sits before being sold.',
    benchmark: 'Lower is generally better. Varies heavily by industry.',
    higher: 'Inventory sits longer — higher carrying costs and obsolescence risk.',
    lower: 'Fast turnover — efficient inventory management.',
    assess: (v) => v <= 60 ? 'good' : v <= 120 ? 'caution' : 'concern',
  },
  'Days Payable Outstanding': {
    what: 'Average days the company takes to pay its suppliers.',
    benchmark: 'Typical: 30–60 days. Very high may strain supplier relationships.',
    higher: 'Holding onto cash longer — good for cash flow but may signal financial stress.',
    lower: 'Paying suppliers quickly — good relationships but less cash flow benefit.',
    assess: (v) => v <= 60 ? 'good' : v <= 90 ? 'caution' : 'concern',
  },
}

function getRatioGuide(name: string): RatioGuide | null {
  return RATIO_GUIDES[name] ?? null
}

function getHealthLabel(assessment: 'good' | 'caution' | 'concern'): { label: string; className: string } {
  switch (assessment) {
    case 'good': return { label: 'Healthy', className: 'text-green-700 bg-green-50 border-green-200' }
    case 'caution': return { label: 'Watch', className: 'text-amber-700 bg-amber-50 border-amber-200' }
    case 'concern': return { label: 'Flag', className: 'text-red-700 bg-red-50 border-red-200' }
  }
}

function computeTrendSummary(years: [string, number | null][]): string {
  const valid = years.filter(([, v]) => v != null) as [string, number][]
  if (valid.length < 2) return ''
  const first = valid[0]
  const last = valid[valid.length - 1]
  const changePct = ((last[1] - first[1]) / Math.abs(first[1])) * 100
  const direction = changePct > 5 ? 'increased' : changePct < -5 ? 'declined' : 'remained stable'
  return `${direction} ${Math.abs(changePct).toFixed(0)}% from ${first[0]} to ${last[0]}`
}

function getSparklineData(result: RatioResultItem) {
  return Object.entries(result.values)
    .filter(([, v]) => v != null)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([yr, v]) => ({ yr, val: Number(v) }))
}

function getChartData(result: RatioResultItem) {
  return Object.entries(result.values)
    .filter(([, v]) => v != null)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([yr, v]) => ({ year: yr, value: Number(v) }))
}

function buildOverlayData(results: RatioResultItem[]) {
  const allYears = new Set<string>()
  for (const r of results) {
    for (const [yr, v] of Object.entries(r.values)) {
      if (v != null) allYears.add(yr)
    }
  }
  const sortedYears = Array.from(allYears).sort((a, b) => Number(a) - Number(b))
  return sortedYears.map((yr) => {
    const point: Record<string, string | number | null> = { year: yr }
    for (const r of results) {
      point[r.name] = r.values[yr as unknown as number] ?? null
    }
    return point
  })
}

export default function Layer4Dashboard({
  ratioResults, companyName, onPrevLayer, onOpenAnalysis, analysisReady, analysisLoading,
}: Layer4DashboardProps) {
  const [selectedRatio, setSelectedRatio] = useState<number>(0)

  const overlayData = useMemo(() => buildOverlayData(ratioResults), [ratioResults])

  if (ratioResults.length === 0) {
    return (
      <div className="data-card p-8 text-center">
        <BarChart3 className="w-12 h-12 text-gray-200 mx-auto mb-3" />
        <p className="text-sm text-gray-500">No ratios computed yet</p>
        <p className="text-xs text-gray-400 mt-1">Go back to Layer 3 to build and compute ratios</p>
        <button
          onClick={onPrevLayer}
          className="mt-4 flex items-center gap-1 mx-auto text-sm text-brand-600 hover:text-brand-700"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Ratio Builder
        </button>
      </div>
    )
  }

  const activeResult = ratioResults[selectedRatio] ?? ratioResults[0]

  return (
    <div className="space-y-4">
      {/* AI coaching bar */}
      <div className="coaching-panel">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-amber-500" />
            <p className="text-sm text-brand-800">
              {analysisReady
                ? 'AI analysis ready — open the panel for insights on these ratios.'
                : `Want AI to interpret ${companyName}'s ratios?`}
            </p>
          </div>
          {!analysisReady && (
            <button
              onClick={onOpenAnalysis}
              disabled={analysisLoading}
              className="px-3 py-1.5 text-xs font-medium text-white bg-brand-600 rounded-lg
                         hover:bg-brand-700 disabled:opacity-50 transition-colors"
            >
              {analysisLoading ? 'Analyzing...' : 'Run AI Analysis'}
            </button>
          )}
        </div>
      </div>

      {/* Ratio summary cards with sparklines */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {ratioResults.map((result, idx) => {
          const years = Object.entries(result.values)
            .filter(([, v]) => v != null)
            .sort(([a], [b]) => Number(b) - Number(a))
          const latest = years[0]
          const suffix = MULTIPLIER_LABELS[result.definition.multiply_by] ?? ''
          const guide = getRatioGuide(result.name)
          const latestVal = latest ? Number(latest[1]) : null
          const health = guide && latestVal != null ? getHealthLabel(guide.assess(latestVal)) : null
          const sparkData = getSparklineData(result)
          const sparkColor = result.trend === 'up' ? '#10b981' : result.trend === 'down' ? '#ef4444' : '#6b7280'

          return (
            <button
              key={idx}
              onClick={() => setSelectedRatio(idx)}
              className={cn(
                'data-card p-3 text-left transition-all',
                selectedRatio === idx && 'ring-2 ring-brand-500 border-brand-300',
              )}
            >
              <div className="flex items-center justify-between mb-1">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider truncate">
                  {result.name}
                </p>
                {health && (
                  <span className={cn('text-[9px] font-semibold px-1.5 py-0.5 rounded border', health.className)}>
                    {health.label}
                  </span>
                )}
              </div>
              <div className="flex items-end justify-between gap-2">
                <div>
                  <span className="text-xl font-bold text-gray-900">
                    {latest ? `${Number(latest[1]).toFixed(2)}${suffix}` : '—'}
                  </span>
                  <div className="flex items-center gap-1 mt-0.5">
                    {result.trend && (
                      <span className={cn(
                        'flex items-center gap-0.5 text-[10px] font-semibold',
                        result.trend === 'up' && 'text-green-600',
                        result.trend === 'down' && 'text-red-600',
                        result.trend === 'stable' && 'text-gray-500',
                      )}>
                        {result.trend === 'up' && <TrendingUp className="w-3 h-3" />}
                        {result.trend === 'down' && <TrendingDown className="w-3 h-3" />}
                        {result.trend === 'stable' && <Minus className="w-3 h-3" />}
                        {result.trend}
                      </span>
                    )}
                    {latest && (
                      <span className="text-[10px] text-gray-400">FY {latest[0]}</span>
                    )}
                  </div>
                </div>
                {sparkData.length >= 3 && (
                  <div className="w-20 h-10 shrink-0">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={sparkData}>
                        <Line
                          type="monotone"
                          dataKey="val"
                          stroke={sparkColor}
                          strokeWidth={1.5}
                          dot={false}
                          isAnimationActive={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </button>
          )
        })}
      </div>

      {/* Multi-ratio overlay chart */}
      {ratioResults.length >= 2 && (
        <div className="data-card overflow-hidden">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-800">All Ratios Over Time</h3>
            <p className="text-[10px] text-gray-400 mt-0.5">Click a line to view details below</p>
          </div>
          <div className="px-2 py-4">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={overlayData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="year"
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  axisLine={{ stroke: '#e5e7eb' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  axisLine={false}
                  tickLine={false}
                  width={45}
                />
                <Tooltip
                  contentStyle={{
                    fontSize: 11,
                    borderRadius: 8,
                    border: '1px solid #e5e7eb',
                    boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                  }}
                  formatter={(value: number) => value.toFixed(2)}
                />
                {ratioResults.map((r, i) => (
                  <Line
                    key={r.name}
                    type="monotone"
                    dataKey={r.name}
                    stroke={CHART_COLORS[i % CHART_COLORS.length]}
                    strokeWidth={selectedRatio === i ? 3 : 1.5}
                    dot={false}
                    activeDot={{ r: 4, onClick: () => setSelectedRatio(i) }}
                    opacity={selectedRatio === i ? 1 : 0.4}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="px-4 pb-3 flex flex-wrap gap-x-4 gap-y-1">
            {ratioResults.map((r, i) => (
              <button
                key={r.name}
                onClick={() => setSelectedRatio(i)}
                className={cn(
                  'flex items-center gap-1.5 text-[11px] transition-opacity',
                  selectedRatio === i ? 'opacity-100 font-semibold' : 'opacity-50 hover:opacity-80',
                )}
              >
                <span
                  className="w-3 h-[3px] rounded-full inline-block"
                  style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }}
                />
                {r.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Active ratio detail */}
      {activeResult && <RatioDetail result={activeResult} companyName={companyName} />}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={onPrevLayer}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-brand-600 transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Ratio Builder
        </button>
      </div>
    </div>
  )
}


function RatioDetail({ result, companyName }: { result: RatioResultItem; companyName: string }) {
  const suffix = MULTIPLIER_LABELS[result.definition.multiply_by] ?? ''
  const chartData = getChartData(result)
  const years = Object.entries(result.values)
    .filter(([, v]) => v != null)
    .sort(([a], [b]) => Number(a) - Number(b))

  const numericVals = years.map(([, v]) => Number(v))
  const latestVal = numericVals.length > 0 ? numericVals[numericVals.length - 1] : null

  const numLabels = result.definition.numerator_terms.map(
    (t) => `${t.sign === '-' ? '- ' : ''}${t.concept.split(':').pop()}`
  ).join(' + ')
  const denLabels = result.definition.denominator_terms.map(
    (t) => `${t.sign === '-' ? '- ' : ''}${t.concept.split(':').pop()}`
  ).join(' + ')

  const guide = getRatioGuide(result.name)
  const health = guide && latestVal != null ? guide.assess(latestVal) : null
  const healthInfo = health ? getHealthLabel(health) : null
  const trendSummary = computeTrendSummary(years as [string, number | null][])

  const areaColor = health === 'good' ? '#10b981' : health === 'concern' ? '#ef4444' : '#6366f1'
  const areaFill = health === 'good' ? '#d1fae5' : health === 'concern' ? '#fee2e2' : '#e0e7ff'

  return (
    <div className="data-card overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-800">{result.name}</h3>
            <p className="text-[10px] text-gray-400 mt-0.5 font-mono">
              ({numLabels}) / ({denLabels}){result.definition.multiply_by !== 1 ? ` × ${result.definition.multiply_by}` : ''}
            </p>
          </div>
          {healthInfo && (
            <div className={cn('flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold', healthInfo.className)}>
              {health === 'good' && <CheckCircle2 className="w-3.5 h-3.5" />}
              {health === 'caution' && <AlertTriangle className="w-3.5 h-3.5" />}
              {health === 'concern' && <AlertTriangle className="w-3.5 h-3.5" />}
              {healthInfo.label}
            </div>
          )}
        </div>
      </div>

      {/* Interpretation panel */}
      {guide && (
        <div className="px-4 py-3 bg-blue-50/50 border-b border-blue-100">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
            <div className="space-y-2 text-xs text-gray-700 leading-relaxed">
              <p><strong>What it measures:</strong> {guide.what}</p>
              <p><strong>Benchmarks:</strong> {guide.benchmark}</p>
              {latestVal != null && (
                <p>
                  <strong>{companyName}&apos;s value ({latestVal.toFixed(2)}{suffix}):</strong>{' '}
                  {health === 'good' ? guide.higher : guide.lower}
                </p>
              )}
              {trendSummary && (
                <p><strong>Trend:</strong> {result.name} has {trendSummary}.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {!guide && trendSummary && (
        <div className="px-4 py-3 bg-gray-50/50 border-b border-gray-100">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
            <p className="text-xs text-gray-600 leading-relaxed">
              <strong>Trend:</strong> This ratio has {trendSummary}.
            </p>
          </div>
        </div>
      )}

      {/* Area chart */}
      {chartData.length >= 2 && (
        <div className="px-2 py-4">
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id={`grad-${result.name}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={areaFill} stopOpacity={0.8} />
                  <stop offset="100%" stopColor={areaFill} stopOpacity={0.1} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="year"
                tick={{ fontSize: 10, fill: '#9ca3af' }}
                axisLine={{ stroke: '#e5e7eb' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#9ca3af' }}
                axisLine={false}
                tickLine={false}
                width={45}
                domain={['auto', 'auto']}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  borderRadius: 8,
                  border: '1px solid #e5e7eb',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                }}
                formatter={(value: number) => [`${value.toFixed(2)}${suffix}`, result.name]}
                labelFormatter={(label) => `FY ${label}`}
              />
              {guide?.refLine != null && (
                <ReferenceLine
                  y={guide.refLine}
                  stroke="#9ca3af"
                  strokeDasharray="6 3"
                  label={{
                    value: guide.refLabel ?? '',
                    position: 'insideTopRight',
                    fontSize: 9,
                    fill: '#9ca3af',
                  }}
                />
              )}
              <Area
                type="monotone"
                dataKey="value"
                stroke={areaColor}
                strokeWidth={2}
                fill={`url(#grad-${result.name})`}
                dot={{ r: 3, fill: areaColor, stroke: '#fff', strokeWidth: 1.5 }}
                activeDot={{ r: 5, fill: areaColor, stroke: '#fff', strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Data table */}
      <div className="border-t border-gray-100">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50">
              <th className="text-left px-4 py-2 text-gray-500 font-semibold uppercase tracking-wider">Year</th>
              <th className="text-right px-4 py-2 text-gray-500 font-semibold uppercase tracking-wider">Value</th>
              <th className="text-right px-4 py-2 text-gray-500 font-semibold uppercase tracking-wider">YoY Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {years.map(([yr, val], idx) => {
              const numVal = Number(val)
              const prevVal = idx > 0 ? Number(years[idx - 1][1]) : null
              const change = prevVal != null && Math.abs(prevVal) > 1e-10
                ? ((numVal - prevVal) / Math.abs(prevVal)) * 100
                : null

              return (
                <tr key={yr}>
                  <td className="px-4 py-2 text-gray-700 font-medium">{yr}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-900">
                    {numVal.toFixed(2)}{suffix}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {change != null ? (
                      <span className={cn(
                        'font-mono',
                        change > 0 ? 'text-green-600' : change < 0 ? 'text-red-600' : 'text-gray-500',
                      )}>
                        {change > 0 ? '+' : ''}{change.toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
