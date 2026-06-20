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

export const REQUEST_ROLES = ['viewer', 'flight_controller', 'mission_commander', 'admin']

function uid() {
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
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
  const text = encodeURIComponent(
    req.status === 'approved'
      ? `DroneArjuna access approved for ${req.username}. Check email/admin for temporary password.`
      : req.status === 'rejected'
      ? `DroneArjuna access request for ${req.username} was rejected. Contact administrator.`
      : `DroneArjuna access request received for ${req.username}. Awaiting admin approval.`,
  )
  return req.mobile ? `sms:${req.mobile}?body=${text}` : ''
}
