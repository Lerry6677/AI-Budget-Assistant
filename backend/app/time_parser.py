import re
from datetime import datetime, timedelta


def parse_expense_time(text: str | None) -> datetime | None:

    if not text:
        return None

    now = datetime.now()

    text = text.strip()

    # =========================
    # 1. 今天 / 昨天 / 前天
    # =========================

    if "今天" in text:
        date = now.date()

    elif "昨天" in text:
        date = (now - timedelta(days=1)).date()

    elif "前天" in text:
        date = (now - timedelta(days=2)).date()

    else:
        date = None

    # =========================
    # 2. 星期
    # =========================

    if date is None:

        weekday_map = {
            "周一": 0,
            "周二": 1,
            "周三": 2,
            "周四": 3,
            "周五": 4,
            "周六": 5,
            "周日": 6,
            "星期一": 0,
            "星期二": 1,
            "星期三": 2,
            "星期四": 3,
            "星期五": 4,
            "星期六": 5,
            "星期日": 6,
            "星期天": 6,
        }

        for key, weekday in weekday_map.items():

            if key in text:

                current_weekday = now.weekday()

                # 上周
                if "上周" in text or "上星期" in text:
                    days = current_weekday + 7 - weekday
                    date = (now - timedelta(days=days)).date()

                # 本周
                elif "本周" in text or "这周" in text:
                    days = current_weekday - weekday
                    date = (now - timedelta(days=days)).date()

                break

    # =========================
    # 3. 明确日期：8月18日
    # =========================

    if date is None:

        match = re.search(
            r"(\d{1,2})月(\d{1,2})日?",
            text
        )

        if match:

            month = int(match.group(1))
            day = int(match.group(2))

            year = now.year

            date = datetime(
                year,
                month,
                day
            ).date()

    # =========================
    # 4. 完整日期：2026年8月18日
    # =========================

    if date is None:

        match = re.search(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日?",
            text
        )

        if match:

            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))

            date = datetime(
                year,
                month,
                day
            ).date()

    # =========================
    # 5. 判断时间段
    # =========================

    if "凌晨" in text:
        hour = 2
        minute = 0

    elif "早上" in text or "早晨" in text:
        hour = 8
        minute = 0

    elif "上午" in text:
        hour = 10
        minute = 0

    elif "中午" in text:
        hour = 12
        minute = 0

    elif "下午" in text:
        hour = 15
        minute = 0

    elif "晚上" in text or "晚" in text:
        hour = 19
        minute = 0

    else:
        hour = None
        minute = 0

    # =========================
    # 没有解析出日期时，如果有时间段则默认为今天，否则返回 None
    # =========================

    if date is None:
        if hour is not None:
            date = now.date()
        else:
            return None

    # 有日期但没有时间段，默认中午
    if hour is None:
        hour = 12
        minute = 0

    return datetime.combine(
        date,
        datetime.min.time().replace(
            hour=hour,
            minute=minute
        )
    )