import { reactive } from 'vue'

export type Session = {
  accessToken: string
  refreshToken: string
  user: { id: string; email: string; name: string }
  workspace: { id: string; name: string; slug: string; role: 'admin' | 'agent' | 'viewer' }
}

const storageKey = 'helpflow.session'

function readSession(): Session | null {
  const rawValue = localStorage.getItem(storageKey)
  if (!rawValue) return null
  try {
    return JSON.parse(rawValue) as Session
  } catch {
    localStorage.removeItem(storageKey)
    return null
  }
}

export const authState = reactive<{ session: Session | null }>({ session: readSession() })

export function setSession(session: Session): void {
  authState.session = session
  localStorage.setItem(storageKey, JSON.stringify(session))
}

export function clearSession(): void {
  authState.session = null
  localStorage.removeItem(storageKey)
}
