import { AlertCircle, CheckCircle2, Download, Filter, Info, Trash2, Warning, Clock } from 'lucide-react'
import { useEventLogStore, type EventCategory, type EventLevel } from '@/store/eventLogStore'
import { useState } from 'react'

export default function SystemLogViewer() {
  const { events, clearOldEvents, exportLogs } = useEventLogStore()
  const [selectedCategory, setSelectedCategory] = useState<EventCategory | 'all'>('all')
  const [selectedLevel, setSelectedLevel] = useState<EventLevel | 'all'>('all')

  const filteredEvents = events.filter(e => {
    if (selectedCategory !== 'all' && e.category !== selectedCategory) return false
    if (selectedLevel !== 'all' && e.level !== selectedLevel) return false
    return true
  })

  const levelIcon = (level: EventLevel) => {
    switch (level) {
      case 'error':
        return <AlertCircle size={14} className="text-red-600" />
      case 'warning':
        return <Warning size={14} className="text-yellow-600" />
      case 'success':
        return <CheckCircle2 size={14} className="text-green-600" />
      default:
        return <Info size={14} className="text-blue-600" />
    }
  }

  const levelBg = (level: EventLevel) => {
    switch (level) {
      case 'error':
        return 'bg-red-50'
      case 'warning':
        return 'bg-yellow-50'
      case 'success':
        return 'bg-green-50'
      default:
        return 'bg-blue-50'
    }
  }

  const handleExport = (format: 'json' | 'csv') => {
    const content = exportLogs(format)
    const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `system-logs.${format}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-hidden">
      {/* Header */}
      <div>
        <h2 className="text-lg font-bold text-slate-900">System Event Logs</h2>
        <p className="text-sm text-slate-600">Audit trail of all system operations and events</p>
      </div>

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="flex gap-2 flex-wrap">
          {/* Category Filter */}
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-slate-500" />
            <select
              value={selectedCategory}
              onChange={e => setSelectedCategory(e.target.value as any)}
              className="da-input text-sm py-1"
            >
              <option value="all">All Categories</option>
              <option value="auth">Auth</option>
              <option value="drone">Drone</option>
              <option value="mission">Mission</option>
              <option value="command">Command</option>
              <option value="system">System</option>
              <option value="connection">Connection</option>
              <option value="telemetry">Telemetry</option>
            </select>
          </div>

          {/* Level Filter */}
          <select
            value={selectedLevel}
            onChange={e => setSelectedLevel(e.target.value as any)}
            className="da-input text-sm py-1"
          >
            <option value="all">All Levels</option>
            <option value="info">Info</option>
            <option value="success">Success</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </div>

        <div className="flex gap-2 ml-auto">
          {/* Export Buttons */}
          <button
            onClick={() => handleExport('json')}
            className="da-btn da-btn-ghost text-xs gap-1"
            title="Export as JSON"
          >
            <Download size={13} />
            JSON
          </button>
          <button
            onClick={() => handleExport('csv')}
            className="da-btn da-btn-ghost text-xs gap-1"
            title="Export as CSV"
          >
            <Download size={13} />
            CSV
          </button>

          {/* Clear Old Events */}
          <button
            onClick={() => clearOldEvents(7)}
            className="da-btn da-btn-ghost text-xs gap-1 text-red-600"
            title="Clear events older than 7 days"
          >
            <Trash2 size={13} />
            Clear
          </button>
        </div>
      </div>

      {/* Event Count */}
      <div className="text-sm text-slate-600">
        Showing <span className="font-semibold">{filteredEvents.length}</span> of{' '}
        <span className="font-semibold">{events.length}</span> total events
      </div>

      {/* Events List */}
      <div className="flex-1 overflow-y-auto border border-slate-200 rounded-lg">
        {filteredEvents.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-500">
            <p>No events found</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-200">
            {filteredEvents.map(event => (
              <div
                key={event.id}
                className={`px-4 py-3 hover:bg-slate-50 transition-colors ${levelBg(event.level)}`}
              >
                <div className="flex items-start gap-3">
                  {/* Icon */}
                  <div className="mt-1">{levelIcon(event.level)}</div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h4 className="font-semibold text-sm text-slate-900">{event.title}</h4>
                      <span className="text-xs px-2 py-0.5 rounded bg-white border border-slate-200 text-slate-600">
                        {event.category}
                      </span>
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-semibold ${
                          event.level === 'error'
                            ? 'bg-red-100 text-red-700'
                            : event.level === 'warning'
                              ? 'bg-yellow-100 text-yellow-700'
                              : event.level === 'success'
                                ? 'bg-green-100 text-green-700'
                                : 'bg-blue-100 text-blue-700'
                        }`}
                      >
                        {event.level}
                      </span>
                    </div>

                    <p className="text-sm text-slate-700 mt-1">{event.description}</p>

                    {/* Metadata */}
                    <div className="flex flex-wrap gap-4 mt-2 text-xs text-slate-500">
                      <div className="flex items-center gap-1">
                        <Clock size={12} />
                        {event.timestamp.toLocaleString()}
                      </div>
                      {event.userId && (
                        <div className="px-2 py-0.5 bg-white border border-slate-200 rounded">
                          User: {event.userId}
                        </div>
                      )}
                      {event.droneId && (
                        <div className="px-2 py-0.5 bg-white border border-slate-200 rounded">
                          Drone: {event.droneId}
                        </div>
                      )}
                      {event.missionId && (
                        <div className="px-2 py-0.5 bg-white border border-slate-200 rounded">
                          Mission: {event.missionId}
                        </div>
                      )}
                    </div>

                    {/* Details */}
                    {event.details && Object.keys(event.details).length > 0 && (
                      <div className="mt-2 text-xs bg-white border border-slate-200 rounded p-2">
                        <p className="font-semibold text-slate-700 mb-1">Details:</p>
                        <pre className="text-slate-600 overflow-x-auto">
                          {JSON.stringify(event.details, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
