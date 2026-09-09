export interface RegisterRequest {
  username: string;
  password: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: number;
  username: string;
  created_at: string;
}

/** GET /user/profile（backend/schemas/user_profile.py::UserProfileResponse） */
export interface UserProfileInfo {
  id: number;
  user_id: string;
  savings_goal: number | null;
  financial_goal: string | null;
  created_at: string;
  updated_at: string;
}