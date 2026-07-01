import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import AppShell from '@/components/layout/AppShell'
import LoginScreen from '@/components/layout/LoginScreen'
import PasswordSetupScreen from '@/components/layout/PasswordSetupScreen'

export default function App() {
  const {
    token,
    hydrate,
    logout,
    setupPending,
    pendingUsername,
    pendingTempPassword,
    pendingEmail,
    pendingMobile,
    completePasswordSetup,
  } = useAuthStore()

  useEffect(() => {
    if (token) hydrate()
  }, [token, hydrate])

  useEffect(() => {
    window.addEventListener('da_auth_expired', logout)
    return () => window.removeEventListener('da_auth_expired', logout)
  }, [logout])

  if (!token) return <LoginScreen />
  if (setupPending && pendingUsername && pendingTempPassword) {
    return (
      <PasswordSetupScreen
        username={pendingUsername}
        tempPassword={pendingTempPassword}
        email={pendingEmail ?? ''}
        mobile={pendingMobile ?? ''}
        onSetupComplete={completePasswordSetup}
      />
    )
  }
  return <AppShell />
}
