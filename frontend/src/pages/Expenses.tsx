import { useCallback, useEffect, useMemo, useState } from 'react';
import { deleteExpense, listExpenses } from '../api/expense';
import type { ExpenseItem } from '../types/expense';
import { formatDateTime, formatMoney, monthKey } from '../utils/format';

// 账单页（V1.0 最小实现）：
// - 列表   → GET /expense（后端不排序，前端按时间倒序）
// - 删除   → DELETE /expense/{id}（后端对不存在记录返回 200 + {success:false}）
// - 筛选   → 月份 / 分类均在前端对列表结果过滤（V1 数据量小，不新增后端接口）
// - 记账创建仍走 AI Chat，本页不提供新增表单。

const ALL = 'all';

/** 条目时间：expense_time 优先，为空回退 created_at */
function itemTime(item: ExpenseItem): string | null {
  return item.expense_time ?? item.created_at ?? null;
}

export default function Expenses() {
  const [items, setItems] = useState<ExpenseItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [monthFilter, setMonthFilter] = useState(ALL);
  const [categoryFilter, setCategoryFilter] = useState(ALL);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listExpenses();
      rows.sort((a, b) => new Date(itemTime(b) ?? 0).getTime() - new Date(itemTime(a) ?? 0).getTime());
      setItems(rows);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : '账单加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 筛选选项从数据派生：月份倒序、分类字典序
  const months = useMemo(() => {
    if (!items) return [];
    const set = new Set<string>();
    for (const it of items) {
      const k = monthKey(itemTime(it));
      if (k) set.add(k);
    }
    return Array.from(set).sort((a, b) => b.localeCompare(a));
  }, [items]);

  const categories = useMemo(() => {
    if (!items) return [];
    return Array.from(new Set(items.map((it) => it.category))).sort((a, b) => a.localeCompare(b, 'zh'));
  }, [items]);

  const filtered = useMemo(() => {
    if (!items) return [];
    return items.filter((it) => {
      if (monthFilter !== ALL && monthKey(itemTime(it)) !== monthFilter) return false;
      if (categoryFilter !== ALL && it.category !== categoryFilter) return false;
      return true;
    });
  }, [items, monthFilter, categoryFilter]);

  const filteredTotal = filtered.reduce((sum, it) => sum + (Number.isFinite(it.amount) ? it.amount : 0), 0);

  const handleDelete = useCallback(
    async (item: ExpenseItem) => {
      if (deletingId !== null) return;
      const ok = window.confirm(`删除这笔账单？\n${item.category} ¥${formatMoney(item.amount)} · ${item.description}`);
      if (!ok) return;
      setDeletingId(item.id);
      setNotice(null);
      try {
        const res = await deleteExpense(item.id);
        if (res.success) {
          // 删除成功：本地同步移除，立即刷新 UI（金额/筛选选项随之更新）
          setItems((prev) => (prev ? prev.filter((r) => r.id !== item.id) : prev));
        } else {
          setNotice('删除失败：记录不存在或已被删除');
          await load(); // 状态未知，重拉保持与后端一致
        }
      } catch (err) {
        setNotice(err instanceof Error && err.message ? err.message : '删除失败，请稍后重试');
      } finally {
        setDeletingId(null);
      }
    },
    [deletingId, load],
  );

  const filterActive = monthFilter !== ALL || categoryFilter !== ALL;

  return (
    <div className="page page-expenses">
      <header className="page-header">
        <span className="page-title">账单</span>
      </header>

      <div className="expenses-body">
        {notice && <div className="stats-error">{notice}</div>}

        {loading && (
          <div className="stats-card">
            <div className="stats-loading">
              <span className="dots">
                <i /> <i /> <i />
              </span>
              正在加载账单…
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

        {!loading && !error && items && items.length === 0 && (
          <div className="stats-card">
            <div className="stats-empty">
              还没有账单记录
              <br />
              去「AI 记账」页面对助手说「今天午饭花了 35 元」试试
            </div>
          </div>
        )}

        {!loading && !error && items && items.length > 0 && (
          <>
            <div className="filter-row">
              <button
                className={`preset-chip ${monthFilter === ALL ? 'is-active' : ''}`}
                type="button"
                onClick={() => setMonthFilter(ALL)}
              >
                全部月份
              </button>
              {months.map((m) => (
                <button
                  key={m}
                  className={`preset-chip ${monthFilter === m ? 'is-active' : ''}`}
                  type="button"
                  onClick={() => setMonthFilter(m)}
                >
                  {m}
                </button>
              ))}
            </div>

            <div className="filter-row">
              <button
                className={`preset-chip ${categoryFilter === ALL ? 'is-active' : ''}`}
                type="button"
                onClick={() => setCategoryFilter(ALL)}
              >
                全部分类
              </button>
              {categories.map((c) => (
                <button
                  key={c}
                  className={`preset-chip ${categoryFilter === c ? 'is-active' : ''}`}
                  type="button"
                  onClick={() => setCategoryFilter(c)}
                >
                  {c}
                </button>
              ))}
            </div>

            <div className="expenses-meta">
              共 {filtered.length} 笔 · ¥{formatMoney(filteredTotal)}
              {filterActive ? '（已筛选）' : ''}
            </div>

            {filtered.length === 0 ? (
              <div className="stats-card">
                <div className="stats-empty">当前筛选条件下没有账单</div>
              </div>
            ) : (
              filtered.map((item) => (
                <div className="expense-item" key={item.id}>
                  <div className="expense-main">
                    <div className="expense-line1">
                      <span className="expense-cat">{item.category}</span>
                      <span className="expense-desc">{item.description || '（无描述）'}</span>
                    </div>
                    <div className="expense-time">{formatDateTime(itemTime(item))}</div>
                  </div>
                  <div className="expense-right">
                    <span className="expense-amount">¥{formatMoney(item.amount)}</span>
                    <button
                      className="expense-delete"
                      type="button"
                      disabled={deletingId === item.id}
                      onClick={() => void handleDelete(item)}
                    >
                      {deletingId === item.id ? '删除中…' : '删除'}
                    </button>
                  </div>
                </div>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
