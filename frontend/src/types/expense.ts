// 与后端 schema 逐字段对齐（backend/schemas/expense.py::ExpenseResponse、
// backend/services/expense_service.py::get_summary / get_month_summary / get_query_summary）。

/** GET /expense 列表项（ExpenseResponse 的 JSON 形态，datetime 序列化为 ISO 字符串） */
export interface ExpenseItem {
  id: number;
  user_id: string;
  category: string;
  amount: number;
  description: string;
  expense_time: string | null;
  expense_time_text: string | null;
  created_at: string;
}

/** GET /summary 与 GET /expense/month 共用形状：category_summary 是 {分类: 金额} 字典 */
export interface SummaryResponse {
  total_amount: number;
  expense_count: number;
  category_summary: Record<string, number>;
}

/** GET /expense/query 的 category_summary 是数组（带占比），与 /summary 不同 */
export interface QueryCategoryEntry {
  category: string;
  amount: number;
  percentage: number;
  expense_count: number;
}

export interface QuerySummaryResponse {
  total_amount: number;
  expense_count: number;
  category_summary: QueryCategoryEntry[];
}
