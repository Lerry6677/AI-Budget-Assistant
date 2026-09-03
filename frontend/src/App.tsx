import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import Chat from './pages/Chat';
import Statistics from './pages/Statistics';
import Profile from './pages/Profile';
import Login from './pages/Login';
import Register from './pages/Register';
import BottomNav from './components/BottomNav';
import NotFound, { ProtectedRoute, GuestOnly } from './pages/NotFound';
import './styles/global.css';

function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      {children}
      <BottomNav />
    </div>
  );
}

function BootScreen() {
  return <div className="boot-screen">加载中…</div>;
}

export default function App() {
  const { isAuthenticated, ready } = useAuth();

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            <>
              <GuestOnly isAuthenticated={isAuthenticated} ready={ready} />
              {!isAuthenticated && !ready ? <BootScreen /> : !isAuthenticated ? <Login /> : null}
            </>
          }
        />
        <Route
          path="/register"
          element={
            <>
              <GuestOnly isAuthenticated={isAuthenticated} ready={ready} />
              {!isAuthenticated && !ready ? <BootScreen /> : !isAuthenticated ? <Register /> : null}
            </>
          }
        />

        <Route
          path="/chat"
          element={
            <MainLayout>
              <ProtectedRoute isAuthenticated={isAuthenticated} ready={ready} />
              {!ready ? <BootScreen /> : isAuthenticated ? <Chat /> : null}
            </MainLayout>
          }
        />
        <Route
          path="/stats"
          element={
            <MainLayout>
              <ProtectedRoute isAuthenticated={isAuthenticated} ready={ready} />
              {!ready ? <BootScreen /> : isAuthenticated ? <Statistics /> : null}
            </MainLayout>
          }
        />
        <Route
          path="/profile"
          element={
            <MainLayout>
              <ProtectedRoute isAuthenticated={isAuthenticated} ready={ready} />
              {!ready ? <BootScreen /> : isAuthenticated ? <Profile /> : null}
            </MainLayout>
          }
        />

        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}