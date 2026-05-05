'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { searchTickers, type TickerResult } from '@/services/api'

interface CompanySearchProps {
  onSearch: (ticker: string) => void
  loading?: boolean
}

export default function CompanySearch({ onSearch, loading = false }: CompanySearchProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<TickerResult[]>([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [searching, setSearching] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 1) {
      setResults([])
      setShowDropdown(false)
      return
    }
    setSearching(true)
    try {
      const data = await searchTickers(q)
      setResults(data)
      setShowDropdown(data.length > 0)
      setHighlightIdx(-1)
    } catch {
      setResults([])
    } finally {
      setSearching(false)
    }
  }, [])

  const handleInputChange = (val: string) => {
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(val), 200)
  }

  const handleSelect = (entry: TickerResult) => {
    setQuery(entry.ticker)
    setShowDropdown(false)
    onSearch(entry.ticker)
  }

  const handleSubmitRaw = () => {
    const ticker = query.trim().toUpperCase()
    if (ticker) {
      setShowDropdown(false)
      onSearch(ticker)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown) {
      if (e.key === 'Enter') {
        e.preventDefault()
        handleSubmitRaw()
      }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightIdx >= 0 && highlightIdx < results.length) {
        handleSelect(results[highlightIdx])
      } else {
        handleSubmitRaw()
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current && !inputRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (results.length) setShowDropdown(true) }}
          placeholder="Search ticker or company..."
          disabled={loading}
          className="pl-9 pr-9 py-2.5 w-72 text-sm border border-gray-300 rounded-lg
                     bg-white focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500
                     placeholder:text-gray-400 disabled:opacity-50"
        />
        {(searching || loading) && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-brand-500 animate-spin" />
        )}
      </div>

      {showDropdown && (
        <div
          ref={dropdownRef}
          className="absolute top-full mt-1.5 left-0 w-[380px] bg-white rounded-xl shadow-2xl
                     ring-1 ring-gray-200 z-50 max-h-80 overflow-y-auto"
        >
          <div className="px-3 py-2 border-b border-gray-100">
            <p className="text-[11px] text-gray-400 font-medium uppercase tracking-wide">
              {results.length} result{results.length !== 1 ? 's' : ''}
            </p>
          </div>
          {results.map((r, i) => (
            <button
              key={`${r.cik}-${r.ticker}`}
              onClick={() => handleSelect(r)}
              className={`w-full text-left px-4 py-2.5 flex items-center justify-between transition-colors
                         border-t border-gray-50 first:border-t-0 ${
                i === highlightIdx ? 'bg-brand-50' : 'hover:bg-gray-50'
              }`}
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-mono font-bold text-brand-600 text-sm shrink-0">{r.ticker}</span>
                <span className="text-gray-700 text-sm truncate">{r.title}</span>
              </div>
              <span className="text-[10px] text-gray-400 font-mono shrink-0 ml-3">CIK {r.cik}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
