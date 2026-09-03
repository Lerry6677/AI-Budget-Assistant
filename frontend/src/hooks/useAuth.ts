import { useCallback, useEffect, useState } from 'react';
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

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    token: null,
    username: null,
    ready: false,
  });

  useEffect(() => {
    const token = getToken();
    setState({ token, username: readUsername(token), ready: true });
  }, []);

  const setSession = useCallback((token: string) => {
    setState({ token, username: readUsername(token), ready: true });
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setState({ token: null, username: null, ready: true });
  }, []);

  return {
    ...state,
    isAuthenticated: !!state.token,
    setSession,
    logout,
  };
}