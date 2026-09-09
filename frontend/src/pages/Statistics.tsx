import { useCallback, useEffect, useState } from 'react';
import { getMonthSummary, getRangeSummary, getSummary } from '../api/expense';
import type { SummaryResponse } from '../types/expense';
import { formatMoney, toLocalISO } from '../utils/format';

// 统计页（V1.0 数据视图）：
// - 全部指标来自后端现有聚合 API，前端不引入图表依赖（纯 CSS 条形图）。
// - 本月概览  → GET /expense/month?year&month
// - 今日支出  → GET /expense/query?start_time&end_time（今日 00:00 → 明日 00:00）
// - 累计支出  → GET /summary
// - 近 6 月趋势 → GET /expense/month × 6（并行）
// - 本月分类占比 → /expense/month 返回的 category_summary（{分类: 金额} 字典）

const TREND_MONTHS = 6;

interface TrendPoint {
  label: string;
  amount: number;
}

interface StatsData {
  all: SummaryResponse;
  month: SummaryResponse;
  todayTotal: number;
  todayCount: number;
  trend: TrendPoint[];
}

async function loadStats(): Promise<StatsData> {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const todayStart = new Date(year, now.getMonth(), now.getDate());
  const tomorrowStart = new Date(year, now.getMonth(), now.getDate() + 1);

  // 近 TREND_MONTHS 个月（含本月），旧 → 新
  const trendMonths: TrendPoint[] = [];
  for (let i = TREND_MONTHS - 1; i >= 0; i--) {
    const d = new Date(year, now.getMonth() - i, 1);
    trendMonths.push({ label: `${d.getMonth() + 1}月`, amount: 0 });
  }

  const [all, monthSummary, today, ...trendResults] = await Promise.all([
    getSummary(),
    getMonthSummary(year, month),
    getRangeSummary(toLocalISO(todayStart), toLocalISO(tomorrowStart)),
    ...trendMonths.map((_, idx) => {
      const d = new Date(year, now.getMonth() - (TREND_MONTHS - 1 - idx), 1);
      return getMonthSummary(d.getFullYear(), d.getMonth() + 1);
    }),
  ]);

  return {
    all,
    month: monthSummary,
    todayTotal: today.total_amount,
    todayCount: today.expense_count,
    trend: trendMonths.map((p, idx) => ({ label: p.label, amount: trendResults[idx].total_amount })),
  };
}

export default function Statistics() {
  const [data, setData] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadStats());
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : '统计数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const now = new Date();
  const monthLabel = `${now.getFullYear()} 年 ${now.getMonth() + 1} 月`;

  // 本月分类：字典 → 数组，按金额降序
  const catEntries: Array<[string, number]> = data
    ? Object.entries(data.month.category_summary).sort((a, b) => b[1] - a[1])
    : [];
  const trendMax = data ? Math.max(...data.trend.map((p) => p.amount), 0) : 0;

  return (
    <div className="page page-stats">
      <header className="page-header">
        <span className="page-title">统计</span>
      </header>

      <div className="stats-body">
        {loading && (
          <div className="stats-card">
            <div className="stats-loading">
              <span className="dots">
                <i /> <i /> <i />
              </span>
              正在加载统计…
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="stats-card">
            <div className="stats-error">{error}</div>
            <button className="retry-chip" type="button" onClick={() => void load()}>
              重试
            </button>
          </div>
        )}

        {!loading && !error && data && data.all.expense_count === 0 && data.todayCount === 0 && (
          <div className="stats-card">
            <div className="stats-empty">
              还没有任何支出记录
              <br />
              去「AI 记账」页面对助手说「今天午饭花了 35 元」试试
            </div>
          </div>
        )}

        {!loading && !error && data && (data.all.expense_count > 0 || data.todayCount > 0) && (
          <>
            {/* 本月概览 */}
            <div className="stats-card">
              <div className="stats-card-head">
                <span className="stats-card-title">{monthLabel}概览</span>
              </div>
              <div className="stat-hero">
                <span className="stat-hero-value">¥{formatMoney(data.month.total_amount)}</span>
                <span className="stat-hero-label">本月支出 · {data.month.expense_count} 笔</span>
              </div>
              <div className="stats-divider" />
              <div className="stat-mini-row">
                <div className="stat-mini">
                  <span className="stat-mini-value">¥{formatMoney(data.todayTotal)}</span>
                  <span className="stat-mini-label">今日 · {data.todayCount} 笔</span>
                </div>
                <div className="stat-mini">
                  <span className="stat-mini-value">¥{formatMoney(data.all.total_amount)}</span>
                  <span className="stat-mini-label">累计 · {data.all.expense_count} 笔</span>
                </div>
              </div>
            </div>

            {/* 近 6 个月趋势（纯 CSS 柱状图） */}
            <div className="stats-card">
              <div className="stats-card-head">
                <span className="stats-card-title">近 {TREND_MONTHS} 个月趋势</span>
              </div>
              <div className="trend-chart">
                {data.trend.map((p) => (
                  <div className="trend-col" key={p.label}>
                    <span className="trend-value">{p.amount > 0 ? formatMoney(p.amount) : ''}</span>
                    <div
                      className="trend-bar"
                      style={{ height: `${trendMax > 0 ? Math.round((p.amount / trendMax) * 100) : 0}%` }}
                    />
                    <span className="trend-label">{p.label}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* 本月分类占比（横向条形） */}
            <div className="stats-card">
              <div className="stats-card-head">
                <span className="stats-card-title">本月分类支出</span>
              </div>
              {catEntries.length === 0 ? (
                <div className="stats-empty">本月还没有分类支出</div>
              ) : (
                catEntries.map(([cat, amount]) => (
                  <div className="cat-row" key={cat}>
                    <span className="cat-name">{cat}</span>
                    <div className="cat-bar-wrap">
                      <div
                        className="cat-bar"
                        style={{
                          width: `${data.month.total_amount > 0 ? Math.round((amount / data.month.total_amount) * 100) : 0}%`,
                        }}
                      />
                    </div>
                    <span className="cat-amount">
                      ¥{formatMoney(amount)} ·{' '}
                      {data.month.total_amount > 0
                        ? Math.round((amount / data.month.total_amount) * 100)
                        : 0}
                      %
                    </span>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
