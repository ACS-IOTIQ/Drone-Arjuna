import { useEffect, useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import AppShell from '@/components/layout/AppShell'
import LoginScreen from '@/components/layout/LoginScreen'
import PasswordSetupScreen from '@/components/layout/PasswordSetupScreen'
import ResetPasswordScreen from '@/components/layout/ResetPasswordScreen'

function readResetTokenFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('token')
}

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
  const [resetToken, setResetToken] = useState<string | null>(readResetTokenFromUrl)

  useEffect(() => {
    if (token) hydrate()
  }, [token, hydrate])

  useEffect(() => {
    window.addEventListener('da_auth_expired', logout)
    return () => window.removeEventListener('da_auth_expired', logout)
  }, [logout])

  const clearResetToken = () => {
    setResetToken(null)
    window.history.replaceState({}, '', window.location.pathname)
  }

  if (resetToken) return <ResetPasswordScreen token={resetToken} onDone={clearResetToken} />
  if (!token) return <LoginScreen />
  if (setupPending && pendingUsername && pendingTempPassword) {
    return (
      <PasswordSetupScreen
        username={pendingUsername}
        tempPassword={pendingTempPassword}
        email={pendingEmail ?? ''}
        mobile={pendingMobile ?? ''}
        onSetupComplete={completePasswordSetup}
        onBack={logout}
      />
    )
  }
  return <AppShell />
}
