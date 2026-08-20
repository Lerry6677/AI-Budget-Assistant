from backend.app.time_parser import parse_expense_time


test_times = [
    "昨天晚上",
    "今天中午",
    "8月18日",
    "上周五",
    "今天早上",
    "前天下午",
    "2026年8月18日",
]


for text in test_times:

    result = parse_expense_time(text)

    print(text, "=>", result)