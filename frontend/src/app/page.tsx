'use client'

import { BookOpen, Calculator } from 'lucide-react'
import ModuleCard from '@/components/ModuleCard'

const MODULES = [
  {
    title: 'Ratio Lab',
    description: 'Browse a public company\'s SEC EDGAR data, build custom financial ratios, chart them over time, and have an LLM analyze the results — the live demo from our final class session.',
    href: '/modules/ratiolab',
    icon: Calculator,
    layers: ['Browse Items', 'Footnotes', 'Build Ratios', 'AI Analysis'],
    active: true,
  },
]

export default function HomePage() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="flex items-center gap-3 mb-1">
            <BookOpen className="w-8 h-8 text-brand-500" />
            <h1 className="text-2xl font-bold text-gray-900">FinSight</h1>
          </div>
          <p className="text-gray-500 ml-11">
            ACCT-GB.2350 — Bonus Session demo: SEC EDGAR data + LLM analysis
          </p>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
          Live Demo
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {MODULES.map((mod) => (
            <ModuleCard key={mod.title} {...mod} />
          ))}
        </div>

        <div className="mt-12 coaching-panel">
          <h3 className="font-semibold text-brand-800 mb-2">How It Works</h3>
          <p className="text-sm text-brand-700 leading-relaxed">
            Pick a public company ticker (try <code className="font-mono text-xs">CAT</code>).
            Browse the line items its filings expose under the SEC&apos;s XBRL schema.
            Pick a few you care about, build a custom ratio, and chart it over the years SEC
            EDGAR has data for. Then click <strong>Run AI Analysis</strong> and watch the LLM
            interpret the numbers. Every step shows the exact XBRL field a number came from
            and the exact prompt the model received — no magic, just an HTTP request.
          </p>
        </div>
      </main>
    </div>
  )
}
