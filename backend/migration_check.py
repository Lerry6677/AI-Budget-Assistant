"""Task 14 Phase 2: ORM vs DB schema consistency check (READ-ONLY).

比较 backend.models 中关键列（user_id）的 ORM 声明
与 MySQL information_schema 实际列定义, 报告任何 drift.

只做 SELECT, 严禁 UPDATE/DELETE/INSERT/TRUNCATE/ALTER/CREATE/DROP.

退出码:
  0  ORM 与 DB schema 一致 (PASS)
  1  发现 drift 或脚本错误 (FAIL)
"""
import sys
sys.path.insert(0, r'd:\study\Projects\AI-Budget-Assistant')

from sqlalchemy import text, inspect
from backend.database import engine
from backend.models.expense import Expense
from backend.models.chat_history import ChatHistory
from backend.models.user import User


def db_column(c, table, column):
    return c.execute(
        text("""
            SELECT COLUMN_NAME, COLUMN_DEFAULT, IS_NULLABLE, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE()
              AND TABLE_NAME=:t
              AND COLUMN_NAME=:c
        """),
        {'t': table, 'c': column}
    ).fetchone()


def orm_column(model, col_name):
    col = model.__table__.c[col_name]
    return {
        'nullable': bool(col.nullable),
        'default': col.default.arg if col.default is not None else None,
        'type_length': getattr(col.type, 'length', None),
    }


def check(label, model, table, col_name, expected_length):
    db = db_column(c, table, col_name)
    orm = orm_column(model, col_name)
    issues = []

    if db is None:
        return label, ['DB COLUMN MISSING'], db, orm

    db_default = db[1]
    db_nullable = db[2] == 'YES'
    db_type = db[3]
    db_length = db[4]

    # nullable
    if orm['nullable'] != db_nullable:
        issues.append(f"nullable drift: ORM={orm['nullable']} DB={db_nullable}")

    # default: ORM 'user001' is forbidden, expect both None
    if orm['default'] is not None:
        issues.append(f"ORM has lingering default={orm['default']!r}, should be None")
    if db_default is not None:
        issues.append(f"DB has unexpected default={db_default!r}")

    # length
    if expected_length is not None and db_length is not None and int(db_length) != int(expected_length):
        issues.append(f"length drift: ORM={expected_length} DB={db_length}")

    return label, issues, db, orm


with engine.connect() as c:
    results = []
    results.append(check('expense.user_id',         Expense,      'expense',      'user_id', 64))
    results.append(check('chat_history.user_id',    ChatHistory,  'chat_history', 'user_id', 50))
    results.append(check('users.id',                User,         'users',        'id',      None))
    results.append(check('users.username',          User,         'users',        'username', None))

    print('=' * 70)
    print('  Task 14 P2: ORM <-> DB schema consistency (READ-ONLY)')
    print('=' * 70)
    total_issues = 0
    for label, issues, db, orm in results:
        if not issues:
            status = 'OK'
        else:
            status = 'DRIFT'
            total_issues += len(issues)
        print(f'\n  [{status}] {label}')
        print(f'    ORM: {orm}')
        print(f'    DB : {db}')
        for x in issues:
            print(f'      - {x}')

    # extra: ensure no NULL user_id rows (would break nullable=False assumption)
    null_expense = c.execute(text("SELECT COUNT(*) FROM expense WHERE user_id IS NULL")).scalar()
    null_chat = c.execute(text("SELECT COUNT(*) FROM chat_history WHERE user_id IS NULL")).scalar()
    print('\n  --- null-check ---')
    print(f'    expense.user_id IS NULL: {null_expense}')
    print(f'    chat_history.user_id IS NULL: {null_chat}')
    if null_expense > 0 or null_chat > 0:
        total_issues += 1
        print('    [DRIFT] existing NULL rows conflict with nullable=False')

    print('\n' + '=' * 70)
    if total_issues == 0:
        print('  RESULT: PASS (ORM == DB schema, no NULL drift)')
    else:
        print(f'  RESULT: FAIL ({total_issues} drift(s) found)')
    print('=' * 70)

    sys.exit(0 if total_issues == 0 else 1)