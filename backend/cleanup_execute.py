"""Task 15 Phase 3: Execute cleanup per user confirmation.

DELETES:
  A. 18 e2e users (id 5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22)
  B. 11 e2e expenses (user_id IN e2e ids)
  C. 15 e2e chats (user_id IN e2e ids)
  D. 40 orphan expenses (user_id IN 'user001','test_user_001','test_time_parse','default','current_user')
  E. 8 orphan chats (user_id IN 'B','X','u1')

PRESERVES:
  - user_id=1 testuser (uncertain)
  - user_id=2 wan9Wang (real user)
  - chat_history WHERE thread_id='main' (real user wan9Wang)
  - user_profile (pending audit)
  - All orphan chat_history.thread_id='main' rows
  - All chat_history rows where user_id=1 or user_id=2

Backup file: backend/backup_deleted_rows_20260906.sql (already generated, 92 rows)
"""
import sys
sys.path.insert(0, r'd:\study\Projects\AI-Budget-Assistant')
from backend.database import engine
from sqlalchemy import text

E2E_USER_IDS = ('5','6','7','8','9','10','11','12','13','14','15','16','17','18','19','20','21','22')
ORPHAN_EXPENSE_USER_IDS = ('user001','test_user_001','test_time_parse','default','current_user')
ORPHAN_CHAT_USER_IDS = ('B','X','u1')

# Two-step delete to avoid FK issues:
#   1. expense and chat_history first (no FK on users)
#   2. users last

def step(c, label, sql, params):
    print(f'  -> {label} ... ', end='', flush=True)
    res = c.execute(text(sql), params)
    print(f'OK (rowcount={res.rowcount})')
    return res.rowcount

with engine.begin() as c:
    print('=' * 70)
    print(' Task 15 Phase 3: EXECUTE cleanup')
    print('=' * 70)
    print()
    print('Pre-snapshot:')
    print(f'  users count: {c.execute(text("SELECT COUNT(*) FROM users")).scalar()}')
    print(f'  expense count: {c.execute(text("SELECT COUNT(*) FROM expense")).scalar()}')
    print(f'  chat_history count: {c.execute(text("SELECT COUNT(*) FROM chat_history")).scalar()}')
    print()
    print('Deleting (in transaction):')
    ph = ','.join(f':u{i}' for i in range(len(E2E_USER_IDS)))
    e2e_p = {f'u{i}': v for i, v in enumerate(E2E_USER_IDS)}

    n1 = step(c, f'DELETE e2e expense (user_id IN e2e ids)',
              f'DELETE FROM expense WHERE user_id IN ({ph})', e2e_p)
    n2 = step(c, f'DELETE e2e chat (user_id IN e2e ids)',
              f'DELETE FROM chat_history WHERE user_id IN ({ph})', e2e_p)
    n3 = step(c, f'DELETE e2e users',
              f'DELETE FROM users WHERE id IN ({ph})', e2e_p)

    ph2 = ','.join(f':u{i}' for i in range(len(ORPHAN_EXPENSE_USER_IDS)))
    p2 = {f'u{i}': v for i, v in enumerate(ORPHAN_EXPENSE_USER_IDS)}
    n4 = step(c, f'DELETE orphan expense (user_id IN {ORPHAN_EXPENSE_USER_IDS})',
              f'DELETE FROM expense WHERE user_id IN ({ph2})', p2)

    ph3 = ','.join(f':u{i}' for i in range(len(ORPHAN_CHAT_USER_IDS)))
    p3 = {f'u{i}': v for i, v in enumerate(ORPHAN_CHAT_USER_IDS)}
    n5 = step(c, f'DELETE orphan chat (user_id IN {ORPHAN_CHAT_USER_IDS})',
              f'DELETE FROM chat_history WHERE user_id IN ({ph3})', p3)

    print()
    print('Post-snapshot:')
    print(f'  users count: {c.execute(text("SELECT COUNT(*) FROM users")).scalar()}')
    print(f'  expense count: {c.execute(text("SELECT COUNT(*) FROM expense")).scalar()}')
    print(f'  chat_history count: {c.execute(text("SELECT COUNT(*) FROM chat_history")).scalar()}')
    print()
    print('Summary of deleted rows:')
    print(f'  e2e expense:           {n1}')
    print(f'  e2e chat:              {n2}')
    print(f'  e2e users:             {n3}')
    print(f'  orphan expense:        {n4}')
    print(f'  orphan chat:           {n5}')
    print(f'  TOTAL:                 {n1+n2+n3+n4+n5}')

print()
print('Transaction committed.')