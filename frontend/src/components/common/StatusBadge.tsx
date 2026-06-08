// ═══════════════════════════════════════════════════════════════
// src/components/common/StatusBadge.tsx
// Reusable pill badge — replaces all inline da-badge divs.
// ═══════════════════════════════════════════════════════════════
import React from 'react'

type Variant = 'success' | 'danger' | 'warning' | 'info' | 'neutral' | 'armed'

interface StatusBadgeProps {
  variant:   Variant
  children:  React.ReactNode
  pulse?:    boolean          // animated pulse dot for ARMED state
  size?:     'xs' | 'sm'
  className?: string
}

const STYLES: Record<Variant, { bg: string; color: string; border: string }> = {
  success: { bg: 'rgba(34,197,94,0.12)',   color: '#22c55e', border: 'rgba(34,197,94,0.25)'  },
  danger:  { bg: 'rgba(239,68,68,0.12)',   color: '#ef4444', border: 'rgba(239,68,68,0.25)'  },
  warning: { bg: 'rgba(245,158,11,0.12)',  color: '#f59e0b', border: 'rgba(245,158,11,0.25)' },
  info:    { bg: 'rgba(59,130,246,0.12)',  color: '#3b82f6', border: 'rgba(59,130,246,0.25)' },
  neutral: { bg: 'rgba(107,114,128,0.15)', color: '#6b7280', border: 'rgba(107,114,128,0.2)' },
  armed:   { bg: 'rgba(239,68,68,0.15)',   color: '#ef4444', border: 'rgba(239,68,68,0.3)'  },
}

export default function StatusBadge({
  variant, children, pulse = false, size = 'sm', className = '',
}: StatusBadgeProps) {
  const s = STYLES[variant]
  const fontSize = size === 'xs' ? '10px' : '11px'
  const padding  = size === 'xs' ? '1px 6px' : '2px 8px'

  return (
    <span
      className={className}
      style={{
        display:      'inline-flex',
        alignItems:   'center',
        gap:          4,
        padding,
        borderRadius: 999,
        fontSize,
        fontWeight:   600,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        background:   s.bg,
        color:        s.color,
        border:       `1px solid ${s.border}`,
      }}>
      {pulse && (
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: s.color,
          animation: 'pulse 1.5s ease-in-out infinite',
          flexShrink: 0,
        }} />
      )}
      {children}
    </span>
  )
}

