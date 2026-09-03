import { Navigate } from 'react-router-dom';

interface Props {
  isAuthenticated: boolean;
  ready: boolean;
}

export function ProtectedRoute({ isAuthenticated, ready }: Props) {
  if (!ready) {
    return <div className="boot-screen">加载中…</div>;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return null;
}

export function GuestOnly({ isAuthenticated, ready }: Props) {
  if (!ready) {
    return <div className="boot-screen">加载中…</div>;
  }
  if (isAuthenticated) {
    return <Navigate to="/chat" replace />;
  }
  return null;
}

export default function NotFound() {
  return <Navigate to="/chat" replace />;
}