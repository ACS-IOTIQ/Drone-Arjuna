
// ═══════════════════════════════════════════════════════════════
// src/components/common/ConfirmModal.tsx
// Generic confirmation dialog with danger / primary variants.
// Usage:
//   <ConfirmModal
//     title="Arm drone"
//     message="The drone will arm its motors. Are you sure?"
//     variant="danger"
//     confirmLabel="Arm"
//     onConfirm={handleArm}
//     onCancel={() => setConfirm(false)}
//   />
// ═══════════════════════════════════════════════════════════════
import { AlertTriangle, Info, X } from 'lucide-react'

interface ConfirmModalProps {
  title:         string
  message:       string
  confirmLabel?: string
  cancelLabel?:  string
  variant?:      'danger' | 'primary'
  onConfirm:     () => void
  onCancel:      () => void
  isLoading?:    boolean
}

export function ConfirmModal({
  title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  variant = 'primary', onConfirm, onCancel, isLoading = false,
}: ConfirmModalProps) {
  const isDanger  = variant === 'danger'
  const accentClr = isDanger ? '#ef4444' : '#3b82f6'
  const btnClass  = isDanger ? 'da-btn da-btn-danger' : 'da-btn da-btn-primary'
  const Icon      = isDanger ? AlertTriangle : Info

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.75)' }}
      onClick={onCancel}>
      <div
        className="da-card w-full max-w-sm p-6"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <Icon size={18} style={{ color: accentClr, flexShrink: 0 }} />
            <h3 className="font-semibold text-sm">{title}</h3>
          </div>
          <button onClick={onCancel}>
            <X size={15} style={{ color: '#6b7280' }} />
          </button>
        </div>

        {/* Message */}
        <p className="text-sm mb-6" style={{ color: '#94a3b8', lineHeight: 1.6 }}>
          {message}
        </p>

        {/* Actions */}
        <div className="flex gap-2">
          <button className="da-btn da-btn-ghost flex-1 justify-center" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            className={`${btnClass} flex-1 justify-center`}
            onClick={onConfirm}
            disabled={isLoading}>
            {isLoading ? 'Processing…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}