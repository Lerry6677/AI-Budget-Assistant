import { request } from './client';
import type { ExpenseItem, SummaryResponse, QuerySummaryResponse } from '../types/expense';

/** GET /expense —— 当前用户全部账单（后端不做排序，前端自行按时间排） */
export function listExpenses(): Promise<ExpenseItem[]> {
  return request<ExpenseItem[]>('/expense');
}

/** DELETE /expense/{id} —— 不存在/越权时后端返回 200 + {success:false} */
export function deleteExpense(id: number): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(`/expense/${id}`, { method: 'DELETE' });
}

/** GET /summary —— 全时段汇总 */
export function getSummary(): Promise<SummaryResponse> {
  return request<SummaryResponse>('/summary');
}

/** GET /expense/month?year&month —— 单月汇总（month 必须 1-12） */
export function getMonthSummary(year: number, month: number): Promise<SummaryResponse> {
  const params = new URLSearchParams({ year: String(year), month: String(month) });
  return request<SummaryResponse>(`/expense/month?${params.toString()}`);
}

/**
 * GET /expense/query?start_time&end_time —— 时间区间汇总。
 * 时间用不带时区的本地 ISO 串（如 2026-09-08T00:00:00），与后端 naive datetime 对齐。
 */
export function getRangeSummary(startTime: string, endTime: string): Promise<QuerySummaryResponse> {
  const params = new URLSearchParams({ start_time: startTime, end_time: endTime });
  return request<QuerySummaryResponse>(`/expense/query?${params.toString()}`);
}
