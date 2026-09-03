import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { login } from '../api/auth';
import { ApiError, setToken } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import AvatarBot from '../components/AvatarBot';

export default function Login() {
  const navigate = useNavigate();
  const { setSession } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码');
      return;
    }
    setLoading(true);
    try {
      const res = await login({ username: username.trim(), password });
      setToken(res.access_token);
      setSession(res.access_token);
      navigate('/chat', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) setError(err.detail);
      else setError('登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-decoration" aria-hidden>
        <span className="orb orb-1" />
        <span className="orb orb-2" />
        <span className="orb orb-3" />
      </div>

      <div className="auth-content">
        <div className="auth-logo">
          <AvatarBot size={88} />
        </div>
        <h1 className="auth-title">AI 记账助手</h1>
        <p className="auth-subtitle">让记账更简单，生活更轻松</p>

        <form className="auth-form" onSubmit={submit}>
          <label className="field">
            <span className="field-label">用户名</span>
            <input
              className="field-input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoComplete="username"
              disabled={loading}
            />
          </label>

          <label className="field">
            <span className="field-label">密码</span>
            <input
              className="field-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
              disabled={loading}
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-btn primary" type="submit" disabled={loading}>
            {loading ? '登录中…' : '登录'}
          </button>

          <div className="auth-switch">
            没有账号？<Link to="/register">注册</Link>
          </div>
        </form>
      </div>
    </div>
  );
}