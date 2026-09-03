import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { register, login } from '../api/auth';
import { ApiError, setToken } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import AvatarBot from '../components/AvatarBot';

export default function Register() {
  const navigate = useNavigate();
  const { setSession } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError('请填写完整信息');
      return;
    }
    if (username.trim().length < 3) {
      setError('用户名至少 3 位');
      return;
    }
    if (password.length < 6) {
      setError('密码至少 6 位');
      return;
    }
    if (password !== confirm) {
      setError('两次密码不一致');
      return;
    }
    setLoading(true);
    try {
      await register({ username: username.trim(), password });
      // auto-login after successful registration
      const res = await login({ username: username.trim(), password });
      setToken(res.access_token);
      setSession(res.access_token);
      navigate('/chat', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) setError(err.detail);
      else setError('注册失败，请稍后重试');
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
          <AvatarBot size={72} />
        </div>
        <h1 className="auth-title">创建账号</h1>
        <p className="auth-subtitle">开启你的 AI 记账之旅</p>

        <form className="auth-form" onSubmit={submit}>
          <label className="field">
            <span className="field-label">用户名</span>
            <input
              className="field-input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="3-50 个字符"
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
              placeholder="至少 6 位"
              autoComplete="new-password"
              disabled={loading}
            />
          </label>

          <label className="field">
            <span className="field-label">确认密码</span>
            <input
              className="field-input"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="再次输入密码"
              autoComplete="new-password"
              disabled={loading}
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-btn primary" type="submit" disabled={loading}>
            {loading ? '注册中…' : '注册'}
          </button>

          <div className="auth-switch">
            已有账号？<Link to="/login">登录</Link>
          </div>
        </form>
      </div>
    </div>
  );
}