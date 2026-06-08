// ═══════════════════════════════════════════
// Sidebar.tsx
// ═══════════════════════════════════════════
import { Layers, Map, Play, BarChart2, Settings, LogOut, Video } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import type { Workspace } from './AppShell'

interface NavItem { id: Workspace; icon: React.ReactNode; label: string }

const NAV: NavItem[] = [
  { id: 'fleet',    icon: <Layers size={20} />,   label: 'Fleet'    },
  { id: 'plan',     icon: <Map size={20} />,       label: 'Plan'     },
  { id: 'fly',      icon: <Play size={20} />,      label: 'Fly'      },
  { id: 'monitor',  icon: <BarChart2 size={20} />, label: 'Monitor'  },
  { id: 'settings', icon: <Settings size={20} />,  label: 'Settings' },
]

interface Props {
  active: Workspace
  onSelect: (w: Workspace) => void
  cameraOpen: boolean
  onCameraToggle: () => void
}

export default function Sidebar({ active, onSelect, cameraOpen, onCameraToggle }: Props) {
  const logout = useAuthStore(s => s.logout)

  return (
    <nav className="flex flex-col items-center py-3 gap-1 shrink-0"
      style={{ width: 56, background: 'var(--da-surface)', borderRight: '1px solid var(--da-border)' }}>

      {/* Logo dot */}
      <div className="w-8 h-8 rounded-lg mb-3 flex items-center justify-center"
        style={{ background: '#3b82f6' }}>
        <span className="text-xs font-bold">DA</span>
      </div>

      {NAV.map(item => (
        <button
          key={item.id}
          title={item.label}
          onClick={() => onSelect(item.id)}
          className="relative flex flex-col items-center justify-center w-10 h-10 rounded-lg transition-all"
          style={{
            color: active === item.id ? '#3b82f6' : '#6b7280',
            background: active === item.id ? 'rgba(59,130,246,0.12)' : 'transparent',
          }}>
          {item.icon}
          {/* Active indicator stripe */}
          {active === item.id && (
            <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r"
              style={{ background: '#3b82f6' }} />
          )}
        </button>
      ))}

      <div className="flex-1" />

      {/* Camera feed toggle */}
      <button
        title={cameraOpen ? 'Hide payload camera' : 'Show payload camera'}
        onClick={onCameraToggle}
        className="w-10 h-10 rounded-lg flex items-center justify-center transition-all mb-1"
        style={{
          color:      cameraOpen ? 'var(--da-teal)' : '#4b5563',
          background: cameraOpen ? 'rgba(32,208,180,0.12)' : 'transparent',
          border:     cameraOpen ? '1px solid rgba(32,208,180,0.3)' : '1px solid transparent',
        }}>
        <Video size={17} />
      </button>

      <button
        title="Sign out"
        onClick={logout}
        className="w-10 h-10 rounded-lg flex items-center justify-center transition-all"
        style={{ color: '#6b7280' }}>
        <LogOut size={18} />
      </button>
    </nav>
  )
}

