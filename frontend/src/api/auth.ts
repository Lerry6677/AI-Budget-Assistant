import { request } from './client';
import type { RegisterRequest, LoginRequest, TokenResponse, UserResponse } from '../types/auth';

export function register(payload: RegisterRequest): Promise<UserResponse> {
  return request<UserResponse>('/register', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}

export function login(payload: LoginRequest): Promise<TokenResponse> {
  return request<TokenResponse>('/login', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}