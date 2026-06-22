import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import AppShell from '@/components/layout/AppShell'
import LoginScreen from '@/components/layout/LoginScreen'
import PasswordSetupScreen from '@/components/layout/PasswordSetupScreen'

export default function App() {
  const { token, hydrate, logout } = useAuthStore()

  useEffect(() => {
    if (token) hydrate()
  }, [token, hydrate])

  useEffect(() => {
    window.addEventListener('da_auth_expired', logout)
    return () => window.removeEventListener('da_auth_expired', logout)
  }, [logout])

  // TODO: Check user.needs_password_setup from your auth store when implemented
  // For now, only show LoginScreen or AppShell
  if (!token) return <LoginScreen />
  return <AppShell />
}
