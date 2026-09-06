import { useEffect, useState } from 'react';
import { clearToken, getToken } from '../api/client';

interface AuthState {
  token: string | null;
  username: string | null;
  ready: boolean;
}

// Lightweight auth state: we only persist JWT in localStorage.
// username is decoded from the JWT payload (sub + username) — no user_id is ever
// invented on the frontend, all data isolation is enforced server-side.
function readUsername(token: string | null): string | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length < 2) return null;
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '==='.slice((payload.length + 3) % 4);
    const json = atob(padded);
    const data = JSON.parse(json) as { username?: string };
    return typeof data.username === 'string' ? data.username : null;
  } catch {
    return null;
  }
}

// Module-level singleton state so every `useAuth()` consumer shares the same
// session and re-renders when it changes.
const listeners = new Set<() => void>();
let state: AuthState = {
  token: getToken(),
  username: readUsername(getToken()),
  ready: true,
};

function emit() {
  for (const fn of listeners) fn();
}

function update(next: AuthState) {
  state = next;
  emit();
}

export function setSession(token: string): void {
  update({ token, username: readUsername(token), ready: true });
}

export function clearSession(): void {
  clearToken();
  update({ token: null, username: null, ready: true });
}

export function useAuth() {
  const [, force] = useState(0);

  useEffect(() => {
    const fn = () => force((n) => n + 1);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);

  return {
    token: state.token,
    username: state.username,
    ready: state.ready,
    isAuthenticated: !!state.token,
    setSession,
    logout: clearSession,
  };
}