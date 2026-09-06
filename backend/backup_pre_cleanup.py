"""Generate a SQL-format backup of all rows about to be deleted.
This script is READ-ONLY: only SELECT against the DB, writes a .sql file.
"""
import sys
from datetime import datetime
sys.path.insert(0, r'd:\study\Projects\AI-Budget-Assistant')
from backend.database import engine
from sqlalchemy import text

OUT = r'd:\study\Projects\AI-Budget-Assistant\backend\backup_deleted_rows_20260906.sql'

E2E_USER_IDS = ('5','6','7','8','9','10','11','12','13','14','15','16','17','18','19','20','21','22')
ORPHAN_EXPENSE_USER_IDS = ('user001','test_user_001','test_time_parse','default','current_user')
ORPHAN_CHAT_USER_IDS = ('B','X','u1')

def esc(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (datetime,)):
        return f"'{v.strftime('%Y-%m-%d %H:%M:%S')}'"
    s = str(v).replace('\\', '\\\\').replace("'", "\\'")
    return f"'{s}'"

def dump_rows(f, table, columns, rows):
    if not rows:
        return 0
    col_list = ', '.join(f'`{c}`' for c in columns)
    f.write(f'-- {table}: {len(rows)} rows\n')
    for r in rows:
        vals = ', '.join(esc(v) for v in r)
        f.write(f'INSERT INTO `{table}` ({col_list}) VALUES ({vals});\n')
    f.write('\n')
    return len(rows)

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(f'-- Backup of rows deleted by cleanup_execute.py\n')
    f.write(f'-- Generated: 2026-09-06 14:56\n')
    f.write(f'-- To restore: re-INSERT these rows back into their tables\n\n')
    f.write('SET FOREIGN_KEY_CHECKS=0;\n\n')

    with engine.connect() as c:
        # E2E users
        ph = ','.join(':u'+str(i) for i in range(len(E2E_USER_IDS)))
        rows = c.execute(text(f"SELECT id, username, password_hash, created_at FROM users WHERE id IN ({ph})"),
                         {f'u{i}':v for i,v in enumerate(E2E_USER_IDS)}).fetchall()
        n = dump_rows(f, 'users', ['id','username','password_hash','created_at'], rows)
        f.write(f'-- e2e users: {n}\n\n')

        # expenses for e2e users
        rows = c.execute(text(f"SELECT id, user_id, category, amount, description, expense_time, expense_time_text, created_at FROM expense WHERE user_id IN ({ph})"),
                         {f'u{i}':v for i,v in enumerate(E2E_USER_IDS)}).fetchall()
        n = dump_rows(f, 'expense', ['id','user_id','category','amount','description','expense_time','expense_time_text','created_at'], rows)
        f.write(f'-- e2e expense: {n}\n\n')

        # chat_history for e2e users
        rows = c.execute(text(f"SELECT id, user_id, thread_id, user_input, agent_reply, created_at FROM chat_history WHERE user_id IN ({ph})"),
                         {f'u{i}':v for i,v in enumerate(E2E_USER_IDS)}).fetchall()
        n = dump_rows(f, 'chat_history', ['id','user_id','thread_id','user_input','agent_reply','created_at'], rows)
        f.write(f'-- e2e chat: {n}\n\n')

        # orphan expenses
        ph2 = ','.join(':u'+str(i) for i in range(len(ORPHAN_EXPENSE_USER_IDS)))
        rows = c.execute(text(f"SELECT id, user_id, category, amount, description, expense_time, expense_time_text, created_at FROM expense WHERE user_id IN ({ph2})"),
                         {f'u{i}':v for i,v in enumerate(ORPHAN_EXPENSE_USER_IDS)}).fetchall()
        n = dump_rows(f, 'expense', ['id','user_id','category','amount','description','expense_time','expense_time_text','created_at'], rows)
        f.write(f'-- orphan expense: {n}\n\n')

        # orphan chats
        ph3 = ','.join(':u'+str(i) for i in range(len(ORPHAN_CHAT_USER_IDS)))
        rows = c.execute(text(f"SELECT id, user_id, thread_id, user_input, agent_reply, created_at FROM chat_history WHERE user_id IN ({ph3})"),
                         {f'u{i}':v for i,v in enumerate(ORPHAN_CHAT_USER_IDS)}).fetchall()
        n = dump_rows(f, 'chat_history', ['id','user_id','thread_id','user_input','agent_reply','created_at'], rows)
        f.write(f'-- orphan chat: {n}\n\n')

    f.write('SET FOREIGN_KEY_CHECKS=1;\n')

import os
print(f'Backup written: {OUT} ({os.path.getsize(OUT)} bytes)')