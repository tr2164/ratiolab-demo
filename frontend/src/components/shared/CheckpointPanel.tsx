'use client'

import { useState, useEffect, useCallback } from 'react'
import { CheckCircle2, XCircle, Send, Loader2, HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  fetchCheckpointQuestions,
  submitCheckpointResponse,
  type CheckpointQuestion,
  type CheckpointResponseResult,
} from '@/services/api'

interface CheckpointPanelProps {
  module: string
  layer: number
  onCompletionChange?: (allAnswered: boolean) => void
}

interface AnsweredState {
  questionId: number
  result: CheckpointResponseResult
  selectedChoice?: string
}

export default function CheckpointPanel({ module, layer, onCompletionChange }: CheckpointPanelProps) {
  const [questions, setQuestions] = useState<CheckpointQuestion[]>([])
  const [loading, setLoading] = useState(true)
  const [answered, setAnswered] = useState<Record<number, AnsweredState>>({})
  const [submitting, setSubmitting] = useState<number | null>(null)
  const [selectedChoices, setSelectedChoices] = useState<Record<number, string>>({})
  const [textInputs, setTextInputs] = useState<Record<number, string>>({})

  useEffect(() => {
    setLoading(true)
    setAnswered({})
    setSelectedChoices({})
    setTextInputs({})
    fetchCheckpointQuestions(module, layer)
      .then(setQuestions)
      .catch(() => setQuestions([]))
      .finally(() => setLoading(false))
  }, [module, layer])

  const handleSubmit = useCallback(async (question: CheckpointQuestion) => {
    setSubmitting(question.id)
    try {
      const body = question.question_type === 'mc'
        ? { selected_choice: selectedChoices[question.id] }
        : { text_response: textInputs[question.id] }

      const result = await submitCheckpointResponse(question.id, body)
      setAnswered(prev => ({
        ...prev,
        [question.id]: {
          questionId: question.id,
          result,
          selectedChoice: selectedChoices[question.id],
        },
      }))
    } catch {
      // silently fail
    } finally {
      setSubmitting(null)
    }
  }, [selectedChoices, textInputs])

  const allAnswered = questions.length > 0 && Object.keys(answered).length >= questions.length

  useEffect(() => {
    onCompletionChange?.(allAnswered)
  }, [allAnswered, onCompletionChange])

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-gray-400">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading questions...
      </div>
    )
  }

  if (questions.length === 0) return null

  const answeredCount = Object.keys(answered).length
  const totalCount = questions.length

  return (
    <div className="border-t border-brand-100 mt-2 pt-3">
      <div className="flex items-center gap-1.5 mb-2.5">
        <HelpCircle className="w-3.5 h-3.5 text-brand-500" />
        <span className="text-xs font-semibold text-brand-700 uppercase tracking-wider">
          Check Your Understanding
        </span>
        {answeredCount > 0 && (
          <span className="ml-auto text-[10px] font-medium text-brand-500 bg-brand-50 px-1.5 py-0.5 rounded-full">
            {answeredCount}/{totalCount}
          </span>
        )}
      </div>

      <div className="space-y-3">
        {questions.map((q) => {
          const ans = answered[q.id]
          const isSubmitting = submitting === q.id

          return (
            <div key={q.id} className="text-sm">
              <p className="text-gray-700 leading-snug mb-2 text-[13px]">{q.question_text}</p>

              {q.question_type === 'mc' && q.choices && (
                <div className="space-y-1.5">
                  {q.choices.map((c) => {
                    const isSelected = selectedChoices[q.id] === c.id
                    const wasSelected = ans?.selectedChoice === c.id
                    const isCorrectChoice = ans && ans.result.correct_answer?.toLowerCase().includes(c.text.toLowerCase().slice(0, 20))

                    let choiceStyle = 'border-gray-200 hover:border-brand-300 hover:bg-brand-50/50'
                    if (ans) {
                      if (wasSelected && ans.result.is_correct) {
                        choiceStyle = 'border-green-300 bg-green-50 text-green-800'
                      } else if (wasSelected && !ans.result.is_correct) {
                        choiceStyle = 'border-red-300 bg-red-50 text-red-800'
                      } else {
                        choiceStyle = 'border-gray-100 text-gray-400'
                      }
                    }

                    return (
                      <button
                        key={c.id}
                        disabled={!!ans || isSubmitting}
                        onClick={() => setSelectedChoices(prev => ({ ...prev, [q.id]: c.id }))}
                        className={cn(
                          'w-full text-left px-3 py-1.5 rounded-lg border text-[12px] transition-all',
                          'disabled:cursor-default',
                          isSelected && !ans && 'border-brand-400 bg-brand-50 ring-1 ring-brand-200',
                          choiceStyle,
                        )}
                      >
                        <span className="font-mono text-[11px] mr-1.5 opacity-50">{c.id.toUpperCase()}.</span>
                        {c.text}
                        {ans && wasSelected && (
                          ans.result.is_correct
                            ? <CheckCircle2 className="inline w-3.5 h-3.5 ml-1.5 text-green-500" />
                            : <XCircle className="inline w-3.5 h-3.5 ml-1.5 text-red-500" />
                        )}
                      </button>
                    )
                  })}
                </div>
              )}

              {q.question_type === 'short_answer' && (
                <textarea
                  disabled={!!ans}
                  value={textInputs[q.id] || ''}
                  onChange={(e) => setTextInputs(prev => ({ ...prev, [q.id]: e.target.value }))}
                  placeholder="Type your answer..."
                  rows={2}
                  className={cn(
                    'w-full px-3 py-2 text-[12px] rounded-lg border border-gray-200 resize-none',
                    'focus:outline-none focus:ring-1 focus:ring-brand-300 focus:border-brand-300',
                    'disabled:bg-gray-50 disabled:text-gray-500',
                  )}
                />
              )}

              {!ans && (
                <button
                  onClick={() => handleSubmit(q)}
                  disabled={
                    isSubmitting ||
                    (q.question_type === 'mc' && !selectedChoices[q.id]) ||
                    (q.question_type === 'short_answer' && !textInputs[q.id]?.trim())
                  }
                  className={cn(
                    'mt-1.5 flex items-center gap-1.5 px-3 py-1 rounded-md text-[11px] font-medium',
                    'bg-brand-600 text-white hover:bg-brand-700 transition-colors',
                    'disabled:opacity-40 disabled:cursor-not-allowed',
                  )}
                >
                  {isSubmitting ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Send className="w-3 h-3" />
                  )}
                  Submit
                </button>
              )}

              {ans && ans.result.explanation && (
                <div className={cn(
                  'mt-2 px-3 py-2 rounded-lg text-[11px] leading-relaxed',
                  ans.result.is_correct === true
                    ? 'bg-green-50 border border-green-200 text-green-800'
                    : ans.result.is_correct === false
                      ? 'bg-red-50 border border-red-200 text-red-800'
                      : 'bg-blue-50 border border-blue-200 text-blue-800',
                )}>
                  {ans.result.is_correct === false && ans.result.correct_answer && (
                    <p className="font-semibold mb-1">Correct answer: {ans.result.correct_answer}</p>
                  )}
                  {q.question_type === 'short_answer' && ans.result.correct_answer && (
                    <p className="font-semibold mb-1">Model answer: {ans.result.correct_answer}</p>
                  )}
                  <p>{ans.result.explanation}</p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function useCheckpointBadge(module: string, layer: number) {
  const [counts, setCounts] = useState({ answered: 0, total: 0 })
  useEffect(() => {
    fetchCheckpointQuestions(module, layer)
      .then(qs => setCounts(prev => ({ ...prev, total: qs.length })))
      .catch(() => {})
  }, [module, layer])
  return counts
}
