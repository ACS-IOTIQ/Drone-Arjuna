import { useEffect, useId, useRef } from 'react'
import { AlertTriangle, Info, X } from 'lucide-react'

interface ConfirmModalProps {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'primary'
  onConfirm: () => void
  onCancel: () => void
  isLoading?: boolean
}

export function ConfirmModal({
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'primary',
  onConfirm,
  onCancel,
  isLoading = false,
}: ConfirmModalProps) {
  const isDanger = variant === 'danger'
  const btnClass = isDanger ? 'da-btn da-btn-danger' : 'da-btn da-btn-primary'
  const Icon = isDanger ? AlertTriangle : Info
  const titleId = useId()
  const messageId = useId()
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    confirmRef.current?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isLoading) onCancel()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isLoading, onCancel])

  return (
    <div
      className="da-modal-backdrop fixed inset-0 z-50 flex items-center justify-center"
      onClick={() => { if (!isLoading) onCancel() }}>
      <div
        className="da-modal-panel da-card w-full max-w-sm"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
        onClick={event => event.stopPropagation()}>
        <div className="da-modal-header">
          <div className={`da-modal-icon ${isDanger ? 'is-danger' : 'is-primary'}`}>
            <Icon size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 id={titleId}>{title}</h3>
            <p id={messageId}>{message}</p>
          </div>
          <button
            type="button"
            className="da-modal-close"
            onClick={onCancel}
            disabled={isLoading}
            aria-label="Close confirmation dialog">
            <X size={16} />
          </button>
        </div>

        <div className="da-modal-actions">
          <button
            type="button"
            className="da-btn da-btn-ghost flex-1 justify-center"
            onClick={onCancel}
            disabled={isLoading}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`${btnClass} flex-1 justify-center`}
            onClick={onConfirm}
            disabled={isLoading}>
            {isLoading && <span className="da-button-spinner" aria-hidden="true" />}
            {isLoading ? 'Processing...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
