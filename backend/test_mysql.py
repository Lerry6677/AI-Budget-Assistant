from app.database import engine


try:

    with engine.connect() as conn:
        print("MySQL connection success")


except Exception as e:

    print("Connection failed:")
    print(e)