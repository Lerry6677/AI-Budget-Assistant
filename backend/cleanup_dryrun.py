"""Task 15: READ-ONLY cleanup dry-run.

扫描 users / expense / chat_history:
 - 分类: E2E测试数据 / 开发测试残留 / 真实用户数据 / 无法确定
 - 输出: 完整 cleanup plan (id, count, 关联)
 - 严禁: DELETE / UPDATE / INSERT / CREATE / DROP
"""
import sys, json
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, r'd:\study\Projects\AI-Budget-Assistant')
from backend.database import engine
from sqlalchemy import text

OUT = Path(r'd:\study\Projects\AI-Budget-Assistant\backend\cleanup_plan.json')

# ============================================================
# 1. E2E 用户: username LIKE 'e2e_%'
# ============================================================
with engine.connect() as c:
    e2e_users = c.execute(text("""
        SELECT id, username, created_at
        FROM users
        WHERE username LIKE 'e2e_%'
        ORDER BY id
    """)).fetchall()

    # ============================================================
    # 2. 真实用户候选: username NOT LIKE 'e2e_%'
    # ============================================================
    real_users = c.execute(text("""
        SELECT id, username, created_at
        FROM users
        WHERE username NOT LIKE 'e2e_%'
        ORDER BY id
    """)).fetchall()

    # ============================================================
    # 3. expense.user_id 全量分布 + 分类
    # ============================================================
    exp_dist = c.execute(text("""
        SELECT user_id, COUNT(*) AS n, MIN(id) AS first_id, MAX(id) AS last_id
        FROM expense
        GROUP BY user_id
        ORDER BY n DESC
    """)).fetchall()

    # ============================================================
    # 4. expense: E2E 用户关联 (user_id IN e2e user ids)
    # ============================================================
    e2e_user_ids = tuple(str(r[0]) for r in e2e_users)
    if e2e_user_ids:
        placeholders = ','.join(f':u{i}' for i in range(len(e2e_user_ids)))
        e2e_exp = c.execute(
            text(f"SELECT id, user_id, amount, description, expense_time, created_at FROM expense WHERE user_id IN ({placeholders}) ORDER BY id"),
            {f'u{i}': v for i, v in enumerate(e2e_user_ids)}
        ).fetchall()
    else:
        e2e_exp = []

    # ============================================================
    # 5. expense: orphan user_id (user_id NOT in users.id AND not a legacy placeholder)
    # ============================================================
    orphan_exp = c.execute(text("""
        SELECT e.id, e.user_id, e.amount, e.description, e.expense_time, e.created_at
        FROM expense e
        LEFT JOIN users u ON u.id = e.user_id
        WHERE u.id IS NULL
        ORDER BY e.user_id, e.id
    """)).fetchall()

    # ============================================================
    # 6. chat_history 分类
    # ============================================================
    ch_dist = c.execute(text("""
        SELECT user_id, thread_id, COUNT(*) AS n
        FROM chat_history
        GROUP BY user_id, thread_id
        ORDER BY user_id, thread_id
    """)).fetchall()

    # chat_history 关联到 E2E 用户
    if e2e_user_ids:
        placeholders = ','.join(f':u{i}' for i in range(len(e2e_user_ids)))
        e2e_ch = c.execute(
            text(f"SELECT id, user_id, thread_id, user_input, created_at FROM chat_history WHERE user_id IN ({placeholders}) ORDER BY id"),
            {f'u{i}': v for i, v in enumerate(e2e_user_ids)}
        ).fetchall()
    else:
        e2e_ch = []

    # chat_history orphan user_id
    orphan_ch_user = c.execute(text("""
        SELECT c.id, c.user_id, c.thread_id, c.user_input, c.created_at
        FROM chat_history c
        LEFT JOIN users u ON u.id = c.user_id
        WHERE u.id IS NULL
        ORDER BY c.user_id, c.id
    """)).fetchall()

    # legacy thread_id (anon_*, main 不属于当前任何 user)
    legacy_thread = c.execute(text("""
        SELECT id, user_id, thread_id, user_input, created_at
        FROM chat_history
        WHERE thread_id IN ('main') OR thread_id LIKE 'anon_%'
        ORDER BY id
    """)).fetchall()

    # ============================================================
    # 7. user_profile (如存在)
    # ============================================================
    has_up = c.execute(text("""
        SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='user_profile'
    """)).scalar() > 0

    if has_up:
        up_dist = c.execute(text("""
            SELECT user_id, COUNT(*) FROM user_profile GROUP BY user_id ORDER BY user_id
        """)).fetchall()
    else:
        up_dist = []

# ============================================================
# 分类
# ============================================================
plan = {
    'timestamp': '2026-09-06',
    'mode': 'DRY-RUN (no DB changes)',
    'summary': {},
    'category_A_e2e': {
        'description': 'E2E 测试数据 (username LIKE e2e_%)',
        'users': [{'id': r[0], 'username': r[1], 'created_at': str(r[2])} for r in e2e_users],
        'expense': [{'id': r[0], 'user_id': r[1], 'amount': str(r[2]), 'description': r[3], 'expense_time': str(r[4]), 'created_at': str(r[5])} for r in e2e_exp],
        'chat_history': [{'id': r[0], 'user_id': r[1], 'thread_id': r[2], 'user_input': r[3], 'created_at': str(r[4])} for r in e2e_ch],
    },
    'category_B_orphan_expense': {
        'description': 'Orphan expense.user_id (user_id 不在 users.id 中, 历史开发残留)',
        'values': sorted({r[1] for r in orphan_exp}),
        'rows': [{'id': r[0], 'user_id': r[1], 'amount': str(r[2]), 'description': r[3], 'expense_time': str(r[4]), 'created_at': str(r[5])} for r in orphan_exp],
    },
    'category_C_orphan_chat': {
        'description': 'Orphan chat_history.user_id (user_id 不在 users.id 中, 历史开发残留)',
        'values': sorted({r[1] for r in orphan_ch_user}),
        'rows': [{'id': r[0], 'user_id': r[1], 'thread_id': r[2], 'user_input': r[3], 'created_at': str(r[4])} for r in orphan_ch_user],
    },
    'category_D_legacy_thread': {
        'description': 'Legacy thread_id (main, anon_*) — 旧 LangGraph 会话命名残留',
        'rows': [{'id': r[0], 'user_id': r[1], 'thread_id': r[2], 'user_input': r[3], 'created_at': str(r[4])} for r in legacy_thread],
    },
    'category_E_real_users': {
        'description': '真实用户候选 (username NOT LIKE e2e_%, 但需用户确认)',
        'users': [{'id': r[0], 'username': r[1], 'created_at': str(r[2])} for r in real_users],
    },
    'expense_distribution': [{'user_id': r[0], 'count': r[1], 'first_id': r[2], 'last_id': r[3]} for r in exp_dist],
    'chat_distribution': [{'user_id': r[0], 'thread_id': r[1], 'count': r[2]} for r in ch_dist],
    'user_profile_distribution': [{'user_id': r[0], 'count': r[1]} for r in up_dist] if has_up else 'TABLE_NOT_FOUND',
}

# 统计
plan['summary'] = {
    'e2e_users_count': len(e2e_users),
    'e2e_expense_count': len(e2e_exp),
    'e2e_chat_count': len(e2e_ch),
    'orphan_expense_user_ids': sorted({r[1] for r in orphan_exp}),
    'orphan_expense_count': len(orphan_exp),
    'orphan_chat_user_ids': sorted({r[1] for r in orphan_ch_user}),
    'orphan_chat_count': len(orphan_ch_user),
    'legacy_thread_count': len(legacy_thread),
    'real_user_candidate_count': len(real_users),
    'real_user_ids': [r[0] for r in real_users],
}

# 写入 JSON
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(plan, f, ensure_ascii=False, indent=2, default=str)

# ============================================================
# 打印人类可读报告
# ============================================================
print('=' * 70)
print(' Task 15 DRY-RUN: 分类审计报告 (READ-ONLY)')
print('=' * 70)

print(f'\n[A] E2E 测试数据')
print(f'    users:    {plan["summary"]["e2e_users_count"]}')
print(f'    expense:  {plan["summary"]["e2e_expense_count"]}')
print(f'    chat:     {plan["summary"]["e2e_chat_count"]}')

print(f'\n[B] Orphan expense.user_id (历史残留)')
print(f'    unique user_id values: {plan["summary"]["orphan_expense_user_ids"]}')
print(f'    total rows:            {plan["summary"]["orphan_expense_count"]}')

print(f'\n[C] Orphan chat_history.user_id')
print(f'    unique user_id values: {plan["summary"]["orphan_chat_user_ids"]}')
print(f'    total rows:            {plan["summary"]["orphan_chat_count"]}')

print(f'\n[D] Legacy thread_id (main, anon_*)')
print(f'    total rows:            {plan["summary"]["legacy_thread_count"]}')

print(f'\n[E] 真实用户候选 (需用户最终确认)')
print(f'    count:                 {plan["summary"]["real_user_candidate_count"]}')
print(f'    user_ids:              {plan["summary"]["real_user_ids"]}')

print(f'\n  详细计划已写入: {OUT}')