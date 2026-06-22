import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Workspace render failed:', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="da-card max-w-md p-5">
          <h2 className="text-base font-semibold text-slate-900">This panel could not load</h2>
          <p className="mt-2 text-sm text-slate-600">
            The rest of DroneArjuna is still running. Try switching panels or sign in again.
          </p>
          <button className="da-btn da-btn-primary mt-4" onClick={() => this.setState({ error: null })}>
            Retry panel
          </button>
        </div>
      </div>
    )
  }
}
