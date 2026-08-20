from app.models import Expense


print(
    Expense.__tablename__
)


print(
    Expense.__table__.columns.keys()
)