/**
 * Connection Health Monitor
 * Tracks WebSocket, telemetry, camera feed, and command channel health
 * Ensures fast, seamless data transfer with automatic reconnection
 */
import { create } from 'zustand'
import { eventLog } from './eventLogStore'
import { notify } from './notificationStore'

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error'

export interface ConnectionMetrics {
  latency: number // ms
  packetsReceived: number
  packetsSent: number
  bytesReceived: number
  bytesSent: number
  packetLoss: number // percentage
  uptime: number // seconds
}

export interface ConnectionChannel {
  id: string
  name: string
  status: ConnectionStatus
  metrics: ConnectionMetrics
  lastUpdate: Date
  retries: number
  maxRetries: number
}

interface ConnectionHealthState {
  channels: Map<string, ConnectionChannel>
  registerChannel: (id: string, name: string) => void
  updateChannelStatus: (id: string, status: ConnectionStatus) => void
  updateMetrics: (id: string, metrics: Partial<ConnectionMetrics>) => void
  getChannel: (id: string) => ConnectionChannel | undefined
  getHealthScore: () => number // 0-100
  getAllHealthy: () => boolean
  retryConnection: (id: string) => void
}

export const useConnectionHealthStore = create<ConnectionHealthState>((set, get) => ({
  channels: new Map(),

  registerChannel: (id, name) => {
    set(state => {
      const newChannels = new Map(state.channels)
      newChannels.set(id, {
        id,
        name,
        status: 'connecting',
        metrics: {
          latency: 0,
          packetsReceived: 0,
          packetsSent: 0,
          bytesReceived: 0,
          bytesSent: 0,
          packetLoss: 0,
          uptime: 0,
        },
        lastUpdate: new Date(),
        retries: 0,
        maxRetries: 5,
      })
      return { channels: newChannels }
    })
  },

  updateChannelStatus: (id, status) => {
    set(state => {
      const newChannels = new Map(state.channels)
      const channel = newChannels.get(id)
      if (channel) {
        channel.status = status
        channel.lastUpdate = new Date()
        
        if (status === 'connected') {
          channel.retries = 0
          notify.success(`${channel.name} Connected`, `${channel.name} is online and responsive`)
          eventLog.connection(`${channel.name} Connected`, `${channel.name} established connection`, undefined, 'success')
        } else if (status === 'disconnected') {
          notify.warning(`${channel.name} Disconnected`, `${channel.name} lost connection`)
          eventLog.connection(`${channel.name} Disconnected`, `${channel.name} lost connection`, undefined, 'warning')
        } else if (status === 'error') {
          notify.danger(`${channel.name} Error`, `${channel.name} encountered an error`)
          eventLog.connection(`${channel.name} Error`, `${channel.name} encountered a connection error`, undefined, 'error')
        }
      }
      return { channels: newChannels }
    })
  },

  updateMetrics: (id, metrics) => {
    set(state => {
      const newChannels = new Map(state.channels)
      const channel = newChannels.get(id)
      if (channel) {
        channel.metrics = { ...channel.metrics, ...metrics }
        channel.lastUpdate = new Date()
      }
      return { channels: newChannels }
    })
  },

  getChannel: (id) => {
    return get().channels.get(id)
  },

  getHealthScore: () => {
    const channels = Array.from(get().channels.values())
    if (channels.length === 0) return 100

    let score = 100
    channels.forEach(ch => {
      if (ch.status === 'connected') {
        score -= ch.metrics.packetLoss * 0.5
        if (ch.metrics.latency > 100) score -= 5
        if (ch.metrics.latency > 200) score -= 10
      } else if (ch.status === 'disconnected') {
        score -= 30
      } else if (ch.status === 'error') {
        score -= 50
      }
    })

    return Math.max(0, Math.min(100, score))
  },

  getAllHealthy: () => {
    const channels = Array.from(get().channels.values())
    return channels.every(ch => ch.status === 'connected' && ch.metrics.packetLoss < 5)
  },

  retryConnection: (id) => {
    const channel = get().getChannel(id)
    if (channel && channel.retries < channel.maxRetries) {
      set(state => {
        const newChannels = new Map(state.channels)
        const ch = newChannels.get(id)
        if (ch) ch.retries++
        return { channels: newChannels }
      })
      eventLog.connection(`Retrying ${channel.name}`, `Attempt ${channel.retries} of ${channel.maxRetries}`)
    }
  },
}))

/**
 * Helper to measure latency
 */
export async function measureLatency(endpoint: string): Promise<number> {
  const start = performance.now()
  try {
    await fetch(endpoint, { method: 'HEAD' })
  } catch (e) {
    // Ignore errors, just measure time
  }
  return performance.now() - start
}

/**
 * WebSocket wrapper with auto-reconnection
 */
export class RobustWebSocket {
  private url: string
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000
  private onOpenCallback: (() => void) | null = null
  private onMessageCallback: ((data: any) => void) | null = null
  private onCloseCallback: (() => void) | null = null
  private onErrorCallback: ((error: Event) => void) | null = null
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null
  private channelId: string

  constructor(url: string, channelId: string) {
    this.url = url
    this.channelId = channelId
    useConnectionHealthStore.getState().registerChannel(channelId, `WebSocket: ${url}`)
  }

  connect() {
    try {
      useConnectionHealthStore.getState().updateChannelStatus(this.channelId, 'connecting')
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this.reconnectAttempts = 0
        useConnectionHealthStore.getState().updateChannelStatus(this.channelId, 'connected')
        this.startHeartbeat()
        this.onOpenCallback?.()
      }

      this.ws.onmessage = (event) => {
        useConnectionHealthStore.getState().updateMetrics(this.channelId, {
          packetsReceived: (useConnectionHealthStore.getState().getChannel(this.channelId)?.metrics.packetsReceived ?? 0) + 1,
          bytesReceived: (useConnectionHealthStore.getState().getChannel(this.channelId)?.metrics.bytesReceived ?? 0) + event.data.length,
        })
        this.onMessageCallback?.(event.data)
      }

      this.ws.onclose = () => {
        this.stopHeartbeat()
        useConnectionHealthStore.getState().updateChannelStatus(this.channelId, 'disconnected')
        this.onCloseCallback?.()
        this.attemptReconnect()
      }

      this.ws.onerror = (event) => {
        useConnectionHealthStore.getState().updateChannelStatus(this.channelId, 'error')
        this.onErrorCallback?.(event)
      }
    } catch (error) {
      useConnectionHealthStore.getState().updateChannelStatus(this.channelId, 'error')
    }
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      useConnectionHealthStore.getState().retryConnection(this.channelId)
      const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1)
      setTimeout(() => this.connect(), delay)
    }
  }

  private startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)
  }

  private stopHeartbeat() {
    if (this.heartbeatInterval) clearInterval(this.heartbeatInterval)
  }

  send(data: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data)
      useConnectionHealthStore.getState().updateMetrics(this.channelId, {
        packetsSent: (useConnectionHealthStore.getState().getChannel(this.channelId)?.metrics.packetsSent ?? 0) + 1,
        bytesSent: (useConnectionHealthStore.getState().getChannel(this.channelId)?.metrics.bytesSent ?? 0) + data.length,
      })
    }
  }

  onOpen(callback: () => void) {
    this.onOpenCallback = callback
  }

  onMessage(callback: (data: any) => void) {
    this.onMessageCallback = callback
  }

  onClose(callback: () => void) {
    this.onCloseCallback = callback
  }

  onError(callback: (error: Event) => void) {
    this.onErrorCallback = callback
  }

  close() {
    this.stopHeartbeat()
    if (this.ws) this.ws.close()
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}
