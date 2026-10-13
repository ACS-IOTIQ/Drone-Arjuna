import { useEffect, useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import AppShell from '@/components/layout/AppShell'
import LoginScreen from '@/components/layout/LoginScreen'
import PasswordSetupScreen from '@/components/layout/PasswordSetupScreen'
import ResetPasswordScreen from '@/components/layout/ResetPasswordScreen'
import { initSystemEventsStream } from '@/store/systemEventsStore'

function readResetTokenFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('token')
}

export default function App() {
  const {
    authenticated,
    ready,
    hydrate,
    logout,
    expireSession,
    setupPending,
    pendingUsername,
    pendingTempPassword,
    pendingEmail,
    pendingMobile,
    completePasswordSetup,
  } = useAuthStore()
  const [resetToken, setResetToken] = useState<string | null>(readResetTokenFromUrl)

  // Ask the server whether the HttpOnly session cookie is still valid.
  useEffect(() => { hydrate() }, [hydrate])

  useEffect(() => {
    if (authenticated) initSystemEventsStream()
  }, [authenticated])

  useEffect(() => {
    window.addEventListener('da_auth_expired', expireSession)
    return () => window.removeEventListener('da_auth_expired', expireSession)
  }, [expireSession])

  const clearResetToken = () => {
    setResetToken(null)
    window.history.replaceState({}, '', window.location.pathname)
  }

  if (resetToken) return <ResetPasswordScreen token={resetToken} onDone={clearResetToken} />
  if (!ready) return null
  if (!authenticated) return <LoginScreen />
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
