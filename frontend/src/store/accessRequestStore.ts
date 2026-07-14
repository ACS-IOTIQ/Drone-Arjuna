export type AccessRequestStatus = 'pending' | 'approved' | 'rejected'

export interface AccessRequest {
  id: string
  username: string
  full_name: string
  email: string
  mobile: string
  requested_role: string
  reason: string
  status: AccessRequestStatus
  created_at: string
  reviewed_at?: string
  admin_note?: string
  temp_password?: string
}

const KEY = 'da_access_requests'
const PW_SETUP_KEY = 'da_password_setup_pending'

export const REQUEST_ROLES = ['viewer', 'flight_controller', 'mission_commander', 'admin']

function uid() {
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

interface PasswordSetupState {
  username: string
  tempPassword: string
  email?: string
  mobile?: string
}

export function getPasswordSetupState(): PasswordSetupState | null {
  try {
    const raw = localStorage.getItem(PW_SETUP_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed?.username && parsed?.tempPassword) return parsed
  } catch {
    // ignore invalid cache
  }
  return null
}

export function setPasswordSetupState(state: PasswordSetupState) {
  localStorage.setItem(PW_SETUP_KEY, JSON.stringify(state))
}

export function clearPasswordSetupState() {
  localStorage.removeItem(PW_SETUP_KEY)
}

export function findApprovedAccessRequest(username: string, password: string) {
  const normalized = username.trim().toLowerCase()
  return listAccessRequests().find(req =>
    req.username.toLowerCase() === normalized &&
    req.status === 'approved' &&
    req.temp_password === password,
  ) ?? null
}

export function isTempPasswordLogin(username: string, password: string) {
  return Boolean(findApprovedAccessRequest(username, password))
}

export function listAccessRequests(): AccessRequest[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function createAccessRequest(input: Omit<AccessRequest, 'id' | 'status' | 'created_at'>) {
  const request: AccessRequest = {
    ...input,
    id: uid(),
    status: 'pending',
    created_at: new Date().toISOString(),
  }
  const next = [request, ...listAccessRequests()]
  localStorage.setItem(KEY, JSON.stringify(next))
  window.dispatchEvent(new Event('da_access_requests_changed'))
  return request
}

export function updateAccessRequest(id: string, patch: Partial<AccessRequest>) {
  const next = listAccessRequests().map(req => req.id === id ? { ...req, ...patch } : req)
  localStorage.setItem(KEY, JSON.stringify(next))
  window.dispatchEvent(new Event('da_access_requests_changed'))
  return next.find(req => req.id === id) ?? null
}

export function pendingAccessRequestCount() {
  return listAccessRequests().filter(req => req.status === 'pending').length
}

export function makeTempPassword(username: string) {
  const suffix = Math.random().toString(36).slice(2, 8)
  const base = username.replace(/[^a-zA-Z0-9]/g, '').slice(0, 8) || 'Operator'
  return `${base}@${suffix}1`
}

export function requestMailto(req: AccessRequest, subjectPrefix = 'DroneArjuna access request') {
  const subject = encodeURIComponent(`${subjectPrefix}: ${req.username}`)
  const body = encodeURIComponent([
    `Name: ${req.full_name}`,
    `Username: ${req.username}`,
    `Email: ${req.email}`,
    `Mobile: ${req.mobile || 'Not provided'}`,
    `Requested role: ${req.requested_role}`,
    `Status: ${req.status}`,
    req.temp_password ? `Temporary password: ${req.temp_password}` : '',
    req.admin_note ? `Admin note: ${req.admin_note}` : '',
    '',
    req.reason ? `Reason:\n${req.reason}` : '',
  ].filter(Boolean).join('\n'))
  return `mailto:${req.email}?subject=${subject}&body=${body}`
}

export function requestSms(req: AccessRequest) {
  if (!req.mobile) return ''

  const message = req.status === 'approved'
    ? `DroneArjuna access approved for ${req.username}. Temporary password: ${req.temp_password}. Please log in and set a new password.`
    : req.status === 'rejected'
    ? `DroneArjuna access request for ${req.username} was rejected. Contact your administrator for details.`
    : `DroneArjuna access request received for ${req.username}. Awaiting admin approval.`

  return `sms:${req.mobile}?body=${encodeURIComponent(message)}`
}

function composeEmailLink(to: string, subject: string, body: string, useGmail = false) {
  const encodedSubject = encodeURIComponent(subject)
  const encodedBody = encodeURIComponent(body)
  if (useGmail) {
    return `https://mail.google.com/mail/?view=cm&fs=1&to=${to}&su=${encodedSubject}&body=${encodedBody}`
  }
  return `mailto:${to}?subject=${encodedSubject}&body=${encodedBody}`
}

function openLink(url: string) {
  if (typeof window === 'undefined' || !url) return
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.target = '_blank'
  anchor.rel = 'noopener noreferrer'
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
}

export function requestGmailLink(req: AccessRequest, subjectPrefix = 'DroneArjuna access request') {
  const subject = `${subjectPrefix}: ${req.username}`
  const body = [
    `Name: ${req.full_name}`,
    `Username: ${req.username}`,
    `Email: ${req.email}`,
    `Mobile: ${req.mobile || 'Not provided'}`,
    `Requested role: ${req.requested_role}`,
    `Status: ${req.status}`,
    req.temp_password ? `Temporary password: ${req.temp_password}` : '',
    req.admin_note ? `Admin note: ${req.admin_note}` : '',
    '',
    req.reason ? `Reason:\n${req.reason}` : '',
  ].filter(Boolean).join('\n')
  return composeEmailLink(req.email, subject, body, true)
}

export function openNotificationChannels(req: AccessRequest) {
  openLink(requestGmailLink(req))
  const sms = requestSms(req)
  if (sms) {
    openLink(sms)
  }
}

export function requestPasswordChangeMailto(email: string, username: string) {
  const subject = `DroneArjuna password changed for ${username}`
  const body = [
    `Hello ${username},`,
    '',
    'Your DroneArjuna password has been successfully updated.',
    'If you did not request this change, contact your administrator immediately.',
    '',
    'Regards,',
    'DroneArjuna Security Team',
  ].join('\n')
  return composeEmailLink(email, subject, body, true)
}

export function requestPasswordChangeSms(mobile: string, username: string) {
  const message = `Your DroneArjuna password for ${username} has been updated. If this was not you, contact your administrator.`
  return `sms:${mobile}?body=${encodeURIComponent(message)}`
}

export function openPasswordChangeNotifications(email: string | undefined, mobile: string | undefined, username: string) {
  if (!email && !mobile) return
  if (email) openLink(requestPasswordChangeMailto(email, username))
  if (mobile) openLink(requestPasswordChangeSms(mobile, username))
}
