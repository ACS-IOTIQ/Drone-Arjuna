import { useState } from 'react'
import DroneTypeManager     from './DroneTypeManager'
import DroneInstanceManager from './DroneInstanceManager'
import VesselManager        from './VesselManager'
import UserManager          from './UserManager'
import { Database, Cpu, Users, Info, Anchor } from 'lucide-react'

type Tab = 'types' | 'instances' | 'vessels' | 'users' | 'about'

const TABS: { id: Tab; label: string; icon: React.ReactNode; group?: string }[] = [
  { id: 'types',     label: 'Drone Types',     icon: <Database size={15} />, group: 'MASTER DATA' },
  { id: 'instances', label: 'Drones',          icon: <Cpu size={15} />,      group: 'MASTER DATA' },
  { id: 'vessels',   label: 'Naval Vessels',   icon: <Anchor size={15} />,   group: 'NAVAL OPS'   },
  { id: 'users',     label: 'Users',           icon: <Users size={15} />,    group: 'SYSTEM'      },
  { id: 'about',     label: 'About',           icon: <Info size={15} />,     group: 'SYSTEM'      },
]

export default function SettingsWorkspace() {
  const [tab, setTab] = useState<Tab>('types')

  const groups = [...new Set(TABS.map(t => t.group!))]

  return (
    <div className="h-full flex overflow-hidden">
      {/* Left sub-nav */}
      <div className="shrink-0 py-4 flex flex-col gap-1 px-2"
        style={{ width: 180, background: 'var(--da-surface)', borderRight: '1px solid var(--da-border)' }}>
        {groups.map(g => (
          <div key={g} className="mb-2">
            <p className="text-[10px] font-semibold px-2 mb-1 mt-2" style={{ color: '#4b5563' }}>{g}</p>
            {TABS.filter(t => t.group === g).map(t => (
              <button key={t.id}
                onClick={() => setTab(t.id)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded text-sm text-left transition-all"
                style={{
                  background: tab === t.id ? 'rgba(59,130,246,0.12)' : 'transparent',
                  color: tab === t.id ? '#3b82f6' : '#6b7280',
                }}>
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        {tab === 'types'     && <DroneTypeManager />}
        {tab === 'instances' && <DroneInstanceManager />}
        {tab === 'vessels'   && <VesselManager />}
        {tab === 'users'     && <UserManager />}
        {tab === 'about'     && <AboutPanel />}
      </div>
    </div>
  )
}

function AboutPanel() {
  return (
    <div className="max-w-lg flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold mb-1">DroneArjuna GCS</h2>
        <p className="text-sm" style={{ color: '#6b7280' }}>
          Military Drone Ground Control System — Version 1.0.0
        </p>
      </div>
      <div className="da-card p-4 flex flex-col gap-2 text-sm">
        {[
          ['Stack',    'FastAPI · React 18 · PostgreSQL · TimescaleDB · Redis · RabbitMQ'],
          ['Protocol', 'MAVLink v1/v2 via pymavlink'],
          ['Maps',     'OpenStreetMap + Leaflet.js'],
          ['Auth',     'JWT · RBAC (4 roles)'],
          ['Spec',     'DroneArjuna-Specs-V2.docx — Phase 1'],
        ].map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <span className="shrink-0 font-medium" style={{ color: '#94a3b8', minWidth: 72 }}>{k}</span>
            <span style={{ color: '#6b7280' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}