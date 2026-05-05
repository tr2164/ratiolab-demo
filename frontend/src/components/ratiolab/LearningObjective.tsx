'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { GraduationCap, X, ChevronRight, ChevronLeft } from 'lucide-react'
import { cn } from '@/lib/utils'
import { LAYERS } from './LayerNav'
import CheckpointPanel from '@/components/shared/CheckpointPanel'

interface LearningObjectiveProps {
  currentLayer: number
  totalLayers: number
  title: string
  children: React.ReactNode
  onPrevLayer?: () => void
  onNextLayer?: () => void
  onCheckpointComplete?: (complete: boolean) => void
}

const MODULE_ID = 'ratiolab'

export default function LearningObjective({
  currentLayer, totalLayers, title, children, onPrevLayer, onNextLayer, onCheckpointComplete,
}: LearningObjectiveProps) {
  const [open, setOpen] = useState(false)
  const [pulse, setPulse] = useState(false)
  const [checkpointDone, setCheckpointDone] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const prevLayerRef = useRef(currentLayer)

  const handleCheckpointChange = useCallback((allAnswered: boolean) => {
    setCheckpointDone(allAnswered)
    onCheckpointComplete?.(allAnswered)
  }, [onCheckpointComplete])

  useEffect(() => {
    if (prevLayerRef.current !== currentLayer) {
      prevLayerRef.current = currentLayer
      setCheckpointDone(false)
      setPulse(true)
      const t = setTimeout(() => setPulse(false), 1500)
      return () => clearTimeout(t)
    }
  }, [currentLayer])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const currentLayerData = LAYERS.find((l) => l.id === currentLayer)

  return (
    <div className="fixed bottom-6 right-6 z-30" ref={panelRef}>
      {open && (
        <div className="absolute bottom-full right-0 mb-3 w-80 max-h-[70vh] bg-white border border-gray-200
                        rounded-xl shadow-2xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200
                        flex flex-col">
          <div className="bg-brand-50 border-b border-brand-100 px-4 py-3 flex-shrink-0">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <GraduationCap className="w-4 h-4 text-brand-600" />
                <span className="text-sm font-semibold text-brand-800">{title}</span>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="p-1 text-brand-400 hover:text-brand-600 rounded transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex items-center gap-1.5">
              {LAYERS.map((layer) => (
                <div
                  key={layer.id}
                  className={cn(
                    'flex-1 h-1.5 rounded-full transition-all duration-300',
                    layer.id <= currentLayer ? 'bg-brand-500' : 'bg-brand-200',
                    layer.id === currentLayer && 'ring-1 ring-brand-400 ring-offset-1',
                  )}
                />
              ))}
            </div>
            <p className="text-[11px] text-brand-500 mt-1.5 font-medium">
              Layer {currentLayer} of {totalLayers}: {currentLayerData?.label}
            </p>
          </div>

          <div className="px-4 py-3 text-sm text-gray-700 leading-relaxed space-y-2 overflow-y-auto flex-1">
            {children}
            <CheckpointPanel module={MODULE_ID} layer={currentLayer} onCompletionChange={handleCheckpointChange} />
          </div>

          <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 bg-gray-50/50 flex-shrink-0">
            <button
              onClick={() => { onPrevLayer?.(); }}
              disabled={currentLayer <= 1}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-brand-600
                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Prev Layer
            </button>
            <button
              onClick={() => { onNextLayer?.(); }}
              disabled={currentLayer >= totalLayers || !LAYERS[currentLayer]?.enabled}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-brand-600
                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              Next Layer
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'relative flex items-center gap-2 pl-3 pr-3.5 py-2.5 rounded-full shadow-lg border-2 transition-all',
          'hover:scale-105 active:scale-95',
          open
            ? 'bg-brand-600 border-brand-600 text-white'
            : 'bg-white border-brand-200 text-brand-600 hover:border-brand-400',
        )}
        aria-label="Learning objective"
      >
        {pulse && !open && (
          <span className="absolute inset-0 rounded-full border-2 border-brand-400 animate-ping opacity-50" />
        )}

        <GraduationCap className="w-5 h-5" />

        <div className="flex items-center gap-1">
          {LAYERS.map((layer) => (
            <div
              key={layer.id}
              className={cn(
                'w-1.5 h-1.5 rounded-full transition-all duration-300',
                layer.id <= currentLayer
                  ? open ? 'bg-white' : 'bg-brand-500'
                  : open ? 'bg-brand-300' : 'bg-gray-300',
                layer.id === currentLayer && 'scale-125',
              )}
            />
          ))}
        </div>
      </button>
    </div>
  )
}
