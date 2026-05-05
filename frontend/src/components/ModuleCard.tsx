'use client'

import Link from 'next/link'
import { type LucideIcon, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ModuleCardProps {
  title: string
  description: string
  href: string
  icon: LucideIcon
  layers: string[]
  active?: boolean
  comingSoon?: boolean
}

export default function ModuleCard({
  title, description, href, icon: Icon, layers, active = true, comingSoon = false,
}: ModuleCardProps) {
  const Wrapper = active ? Link : 'div'

  return (
    <Wrapper
      href={active ? href : '#'}
      className={cn(
        'data-card group block p-6 transition-all',
        active && 'hover:shadow-md hover:border-brand-300 cursor-pointer',
        comingSoon && 'opacity-60 cursor-default',
      )}
    >
      <div className="flex items-start justify-between mb-4">
        <div className={cn(
          'p-3 rounded-xl',
          active ? 'bg-brand-100 text-brand-600' : 'bg-gray-100 text-gray-400',
        )}>
          <Icon className="w-6 h-6" />
        </div>
        {comingSoon && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 uppercase tracking-wide">
            Coming Soon
          </span>
        )}
        {active && (
          <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-brand-500 transition-colors" />
        )}
      </div>

      <h3 className="text-lg font-bold text-gray-900 mb-1">{title}</h3>
      <p className="text-sm text-gray-500 mb-4">{description}</p>

      <div className="flex flex-wrap gap-1.5">
        {layers.map((layer, i) => (
          <span
            key={i}
            className={cn(
              'text-[11px] px-2 py-0.5 rounded-full font-medium',
              active
                ? 'bg-brand-50 text-brand-700 border border-brand-200'
                : 'bg-gray-50 text-gray-400 border border-gray-200',
            )}
          >
            {layer}
          </span>
        ))}
      </div>
    </Wrapper>
  )
}
