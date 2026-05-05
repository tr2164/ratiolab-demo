'use client'

import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { X, Sparkles, Loader2, ChevronRight, Lightbulb, AlertCircle, Send } from 'lucide-react'
import { cn } from '@/lib/utils'
import { chatAboutRatios, type RatioAnalysisResult, type ChatMessage } from '@/services/api'

interface AnalysisPanelProps {
  open: boolean
  onClose: () => void
  analysis: RatioAnalysisResult | null
  loading: boolean
  error: string | null
  companyName: string
  ticker: string
  layerLabel: string
  ratioContext: string
  disclosureContext?: string
  onRetry?: () => void
}

export default function AnalysisPanel({
  open, onClose, analysis, loading, error, companyName, ticker, layerLabel, ratioContext,
  disclosureContext, onRetry,
}: AnalysisPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const isDisclosureMode = !!disclosureContext
  const chatEnabled = isDisclosureMode || !!analysis

  useEffect(() => {
    setMessages([])
    setInput('')
    scrollAreaRef.current?.scrollTo({ top: 0 })
  }, [analysis, ticker, layerLabel, disclosureContext])

  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => {
        scrollAreaRef.current?.scrollTo({ top: 0 })
      })
    }
  }, [open])

  const prevMsgCount = useRef(0)
  useEffect(() => {
    if (messages.length > prevMsgCount.current && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
    prevMsgCount.current = messages.length
  }, [messages])

  const sendMessage = async (text: string, existingMessages: ChatMessage[] = messages) => {
    if (!text || sending) return

    const userMsg: ChatMessage = { role: 'user', content: text }
    const updatedMessages = [...existingMessages, userMsg]
    setMessages(updatedMessages)
    setInput('')
    setSending(true)

    const context = isDisclosureMode ? disclosureContext : ratioContext
    const contextType = isDisclosureMode ? 'disclosure' as const : 'ratios' as const

    try {
      const reply = await chatAboutRatios(ticker, updatedMessages, context, contextType)
      setMessages((prev) => [...prev, reply])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I wasn\'t able to process that. Please try again.' },
      ])
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  const handleSend = () => {
    const text = input.trim()
    if (text) sendMessage(text)
  }

  const handleExplainDisclosure = () => {
    sendMessage('Explain this financial disclosure in plain language. What is it about, what are the key numbers, and what should I pay attention to?', [])
  }

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 bg-black/20 z-30 transition-opacity"
          onClick={onClose}
        />
      )}

      <div
        className={cn(
          'fixed top-0 right-0 h-full w-[420px] max-w-[90vw] bg-white border-l border-gray-200',
          'shadow-2xl z-40 flex flex-col transition-transform duration-300 ease-in-out',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 bg-gray-50/80 shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-amber-500" />
              <h3 className="font-semibold text-gray-900 text-sm">AI Analysis</h3>
            </div>
            <p className="text-[11px] text-gray-400 mt-0.5 ml-6">{companyName} &middot; {layerLabel}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div ref={scrollAreaRef} className="flex-1 overflow-y-auto">
          {loading && (
            <div className="flex flex-col items-center justify-center py-16 px-5">
              <Loader2 className="w-6 h-6 text-amber-500 animate-spin mb-3" />
              <p className="text-sm text-gray-500">Analyzing ratios for {companyName}...</p>
            </div>
          )}

          {error && (
            <div className="p-5">
              <div className="flex items-start gap-2 text-red-600">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium">Analysis unavailable</p>
                  <p className="text-xs mt-1 text-red-500">{error}</p>
                  {onRetry && (
                    <button
                      onClick={onRetry}
                      className="mt-3 px-3 py-1.5 text-xs font-medium text-white bg-brand-600
                                 rounded-lg hover:bg-brand-700 transition-colors"
                    >
                      Retry Analysis
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {!loading && !error && !analysis && !isDisclosureMode && (
            <div className="flex flex-col items-center justify-center py-16 px-5 text-center">
              <Sparkles className="w-8 h-8 text-gray-200 mb-3" />
              <p className="text-sm font-medium text-gray-500 mb-1">AI analysis not yet loaded</p>
              <p className="text-xs text-gray-400 mb-4">
                Build some ratios first, then run AI analysis
              </p>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="px-4 py-2 text-sm font-medium text-white bg-brand-600
                             rounded-lg hover:bg-brand-700 transition-colors flex items-center gap-2"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  Run AI Analysis
                </button>
              )}
            </div>
          )}

          {isDisclosureMode && messages.length === 0 && !sending && (
            <div className="flex flex-col items-center justify-center py-16 px-5 text-center">
              <Sparkles className="w-8 h-8 text-amber-200 mb-3" />
              <p className="text-sm font-medium text-gray-700 mb-1">
                AI Disclosure Assistant
              </p>
              <p className="text-xs text-gray-400 mb-5 max-w-[280px]">
                Get an AI explanation of the disclosure you&apos;re currently viewing, or ask your own questions about it.
              </p>
              <button
                onClick={handleExplainDisclosure}
                className="px-4 py-2.5 text-sm font-medium text-white bg-brand-600
                           rounded-lg hover:bg-brand-700 transition-colors flex items-center gap-2"
              >
                <Sparkles className="w-3.5 h-3.5" />
                Explain This Disclosure
              </button>
            </div>
          )}

          {analysis && (
            <div className="divide-y divide-gray-100">
              <div className="p-5">
                <p className="text-sm text-gray-700 leading-relaxed">{analysis.summary}</p>
              </div>

              {analysis.ratio_highlights.length > 0 && (
                <div className="p-5">
                  <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5">
                    Key Findings
                  </h4>
                  <ul className="space-y-1.5">
                    {analysis.ratio_highlights.map((h, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-gray-600">
                        <ChevronRight className="w-3 h-3 text-brand-400 shrink-0 mt-0.5" />
                        <span>{h}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {analysis.observations.length > 0 && (
                <div className="p-5 space-y-4">
                  <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    What to Notice
                  </h4>
                  {analysis.observations.map((obs, i) => (
                    <div key={i} className="bg-gray-50 rounded-lg p-3.5">
                      <p className="text-xs font-semibold text-gray-800 mb-1">{obs.title}</p>
                      <p className="text-xs text-gray-600 leading-relaxed">{obs.insight}</p>
                      <p className="text-[11px] text-brand-600 mt-2 flex items-start gap-1">
                        <Lightbulb className="w-3 h-3 shrink-0 mt-0.5" />
                        {obs.follow_up}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {messages.length > 0 && (
            <div className="border-t border-gray-200">
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={cn(
                    'px-5 py-4 border-b border-gray-100',
                    msg.role === 'user' ? 'bg-brand-50/50' : 'bg-white',
                  )}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wider mb-2 text-gray-400">
                    {msg.role === 'user' ? 'You' : 'AI'}
                  </p>
                  {msg.role === 'user' ? (
                    <p className="text-xs text-gray-800 leading-relaxed">{msg.content}</p>
                  ) : (
                    <div className="chat-prose">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  )}
                </div>
              ))}
              {sending && (
                <div className="px-5 py-4 bg-white border-b border-gray-100">
                  <p className="text-[10px] font-semibold uppercase tracking-wider mb-1.5 text-gray-400">AI</p>
                  <Loader2 className="w-4 h-4 text-amber-500 animate-spin" />
                </div>
              )}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {chatEnabled && (
          <div className="shrink-0 border-t border-gray-200 bg-white px-4 py-3">
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                placeholder={isDisclosureMode
                  ? 'Ask about this disclosure...'
                  : 'Ask about these ratios, trends, what they mean...'}
                className="flex-1 text-sm px-3 py-2 border border-gray-200 rounded-lg
                           focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500
                           placeholder:text-gray-400"
                disabled={sending}
              />
              <button
                onClick={handleSend}
                disabled={sending || !input.trim()}
                className="p-2.5 bg-brand-600 text-white rounded-lg hover:bg-brand-700
                           disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-1.5 ml-1">
              {isDisclosureMode
                ? `The AI has context on ${companyName}'s disclosure you're viewing`
                : `The AI has context on ${companyName}'s financial ratios and SEC data`}
            </p>
          </div>
        )}
      </div>
    </>
  )
}
