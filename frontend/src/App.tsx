import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import AppShell from '@/components/layout/AppShell'
import LoginScreen from '@/components/layout/LoginScreen'

export default function App() {
  const { token, hydrate } = useAuthStore()

  useEffect(() => {
    if (token) hydrate()
  }, [token])

  if (!token) return <LoginScreen />
  return <AppShell />
}