import { Activity, LogOut, MapPinned, Plane, Radar, Settings, Video } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import type { Workspace } from './AppShell'

interface NavItem { id: Workspace; icon: React.ReactNode; label: string }

const NAV: NavItem[] = [
  { id: 'fleet',    icon: <Radar size={20} />,     label: 'Fleet'    },
  { id: 'plan',     icon: <MapPinned size={20} />, label: 'Plan'     },
  { id: 'fly',      icon: <Plane size={20} />,     label: 'Fly'      },
  { id: 'monitor',  icon: <Activity size={20} />,  label: 'Monitor'  },
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
    <nav
      className="da-sidebar flex shrink-0 flex-col gap-1 py-3"
      aria-label="Primary navigation"
      onTransitionEnd={event => {
        if (event.propertyName === 'width') window.dispatchEvent(new Event('resize'))
      }}>
      <div className="da-sidebar-brand">
        <div className="da-brand-mark">DA</div>
        <div className="da-sidebar-copy">
          <span className="da-sidebar-name">DroneArjuna</span>
          <span className="da-sidebar-caption">Ground control</span>
        </div>
      </div>

      {NAV.map(item => (
        <button
          key={item.id}
          title={item.label}
          aria-current={active === item.id ? 'page' : undefined}
          onClick={() => onSelect(item.id)}
          className={`da-nav-item ${active === item.id ? 'is-active' : ''}`}>
          <span className="da-nav-icon">{item.icon}</span>
          <span className="da-nav-label">{item.label}</span>
          {active === item.id && <span className="da-nav-indicator" />}
        </button>
      ))}

      <div className="flex-1" />

      <button
        title={cameraOpen ? 'Hide payload camera' : 'Show payload camera'}
        aria-pressed={cameraOpen}
        onClick={onCameraToggle}
        className={`da-nav-item ${cameraOpen ? 'is-live' : ''}`}>
        <span className="da-nav-icon"><Video size={18} /></span>
        <span className="da-nav-label">Camera</span>
      </button>

      <button title="Sign out" onClick={logout} className="da-nav-item da-nav-signout">
        <span className="da-nav-icon"><LogOut size={18} /></span>
        <span className="da-nav-label">Sign out</span>
      </button>
    </nav>
  )
}
