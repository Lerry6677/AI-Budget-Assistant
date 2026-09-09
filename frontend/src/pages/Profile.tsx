import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { getUserProfile } from '../api/profile';
import type { UserProfileInfo } from '../types/auth';
import { formatDate, formatMoney } from '../utils/format';
import AvatarBot from '../components/AvatarBot';

// 我的页（V1.0 收尾）：
// - 保留：用户名（JWT 解出）、退出登录
// - 接入：GET /user/profile 展示注册时间；savings_goal / financial_goal 仅在已设置时展示
// - 删除：原先 4 个"点击跳 /chat"的占位入口（历史记录/预算管理/分类管理/设置），
//   预算管理、分类管理、设置留待后续阶段实现真实页面后再加回。

export default function Profile() {
  const navigate = useNavigate();
  const { username, logout } = useAuth();
  const [profile, setProfile] = useState<UserProfileInfo | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setProfileLoading(true);
    setProfileError(null);
    try {
      setProfile(await getUserProfile());
    } catch (err) {
      setProfileError(err instanceof Error && err.message ? err.message : '资料加载失败');
    } finally {
      setProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const joined = formatDate(profile?.created_at);

  return (
    <div className="page page-profile">
      <header className="page-header">
        <span className="page-title">我的</span>
      </header>

      <div className="profile-body">
        <div className="profile-hero">
          <div className="profile-avatar">
            <AvatarBot size={56} />
          </div>
          <div className="profile-meta">
            <div className="profile-name">{username || '未登录'}</div>
            <div className="profile-sub">让记账更简单，生活更轻松</div>
          </div>
        </div>

        <div className="profile-card">
          <div className="profile-row">
            <span className="profile-row-label">注册时间</span>
            <span className="profile-row-value">{profileLoading ? '加载中…' : (joined ?? '—')}</span>
          </div>
          {profile && profile.savings_goal !== null && (
            <div className="profile-row">
              <span className="profile-row-label">储蓄目标</span>
              <span className="profile-row-value">¥{formatMoney(profile.savings_goal)}</span>
            </div>
          )}
          {profile && profile.financial_goal && (
            <div className="profile-row">
              <span className="profile-row-label">理财目标</span>
              <span className="profile-row-value">{profile.financial_goal}</span>
            </div>
          )}
        </div>

        {profileError && (
          <div className="profile-error">
            <span>{profileError}</span>
            <button className="retry-chip" type="button" onClick={() => void load()}>
              重试
            </button>
          </div>
        )}

        <button className="logout-btn" type="button" onClick={handleLogout}>
          退出登录
        </button>
      </div>
    </div>
  );
}
