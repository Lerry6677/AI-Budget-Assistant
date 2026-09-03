import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

interface Item {
  path: string;
  label: string;
  icon: React.ReactNode;
}

const ICON_AI = (
  <svg viewBox="0 0 24 24" fill="none" width="22" height="22">
    <path d="M12 3l1.6 4.6L18 9l-4.4 1.4L12 15l-1.6-4.6L6 9l4.4-1.4L12 3z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    <circle cx="18" cy="17" r="2" stroke="currentColor" strokeWidth="1.6" />
    <circle cx="6" cy="17" r="1.5" stroke="currentColor" strokeWidth="1.6" />
  </svg>
);
const ICON_STATS = (
  <svg viewBox="0 0 24 24" fill="none" width="22" height="22">
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);
const ICON_ME = (
  <svg viewBox="0 0 24 24" fill="none" width="22" height="22">
    <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.6" />
    <path d="M4 21c1.5-4 5-6 8-6s6.5 2 8 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

const ITEMS: Item[] = [
  { path: '/chat', label: 'AI 记账', icon: ICON_AI },
  { path: '/stats', label: '统计', icon: ICON_STATS },
  { path: '/profile', label: '我的', icon: ICON_ME },
];

export default function BottomNav() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <nav className="bottom-nav">
      {ITEMS.map((item) => {
        const active = location.pathname === item.path;
        return (
          <button
            key={item.path}
            className={`nav-item ${active ? 'is-active' : ''}`}
            onClick={() => navigate(item.path)}
            type="button"
          >
            <span className="nav-icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}