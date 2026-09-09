import { request } from './client';
import type { UserProfileInfo } from '../types/auth';

/** GET /user/profile —— 无 profile 记录时后端返回默认对象（goals 为 null，id 为 0） */
export function getUserProfile(): Promise<UserProfileInfo> {
  return request<UserProfileInfo>('/user/profile');
}
