import os
import json
import csv
import io
import re
import urllib.request
import urllib.parse

from datetime import date, datetime


# ==================================================
# 基本设置
# ==================================================

TODAY = date.today()
CURRENT_YEAR = TODAY.year

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")


if not ALPHA_VANTAGE_KEY:
    raise RuntimeError("没有找到 ALPHA_VANTAGE_KEY")

if not FRED_API_KEY:
    raise RuntimeError("没有找到 FRED_API_KEY")


print("=" * 65)
print("🇺🇸 US MARKET CALENDAR")
print("Calendar updater starting...")
print("=" * 65)

print("✅ Alpha Vantage Key 已读取")
print("✅ FRED API Key 已读取")
print()


# ==================================================
# 最终事件列表
# ==================================================

events = []


# ==================================================
# 1. ALPHA VANTAGE
# 大公司财报
# ==================================================

WATCHLIST = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "AVGO",
    "JPM",
    "BAC",
    "V",
    "MA",
    "WMT",
    "COST",
    "NFLX",
    "AMD",
    "ORCL",
    "CRM",
    "XOM",
    "LLY"
]


def fetch_earnings():

    print("📊 正在读取大公司财报日历...")

    params = urllib.parse.urlencode({
        "function": "EARNINGS_CALENDAR",
        "horizon": "3month",
        "apikey": ALPHA_VANTAGE_KEY
    })

    url = "https://www.alphavantage.co/query?" + params

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        text = response.read().decode(
            "utf-8",
            errors="ignore"
        )

    if "symbol,name,reportDate" not in text[:200]:

        print("⚠️ Alpha Vantage 返回异常，本次跳过财报数据")
        print(text[:300])
        return

    reader = csv.DictReader(
        io.StringIO(text)
    )

    count = 0

    for row in reader:

        symbol = (
            row.get("symbol") or ""
        ).strip().upper()

        if symbol not in WATCHLIST:
            continue

        report_date = (
            row.get("reportDate") or ""
        ).strip()

        if not report_date:
            continue

        time_of_day = (
            row.get("timeOfTheDay") or ""
        ).strip().lower()

        if time_of_day == "pre-market":
            session = "pre-market"

        elif time_of_day == "post-market":
            session = "post-market"

        else:
            session = "tbd"

        estimate = (
            row.get("estimate") or ""
        ).strip()

        name = (
            row.get("name") or ""
        ).strip()

        events.append({
            "date": report_date,
            "category": "earnings",
            "importance": "high",
            "title": f"{symbol} Earnings",
            "symbol": symbol,
            "company": name,
            "session": session,
            "estimateEPS": estimate,
            "source": "Alpha Vantage"
        })

        count += 1

    print(f"✅ 财报：找到 {count} 个事件")


# ==================================================
# 2. FRED
# CPI / PPI / NFP / JOLTS / GDP / PCE
# ==================================================

FRED_RELEASES = {

    10: {
        "title": "CPI",
        "fullName": "Consumer Price Index",
        "importance": "critical"
    },

    46: {
        "title": "PPI",
        "fullName": "Producer Price Index",
        "importance": "high"
    },

    50: {
        "title": "Nonfarm Payrolls",
        "fullName": "Employment Situation",
        "importance": "critical"
    },

    53: {
        "title": "GDP",
        "fullName": "Gross Domestic Product",
        "importance": "high"
    },

    54: {
        "title": "PCE",
        "fullName": "Personal Income and Outlays",
        "importance": "critical"
    },

    192: {
        "title": "JOLTS",
        "fullName": "Job Openings and Labor Turnover Survey",
        "importance": "high"
    }
}


def fetch_fred():

    print()
    print("🇺🇸 正在读取 FRED 宏观经济日历...")

    params = urllib.parse.urlencode({
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "include_release_dates_with_no_data": "true",
        "realtime_start": TODAY.isoformat(),
        "limit": 1000,
        "order_by": "release_date",
        "sort_order": "asc"
    })

    url = (
        "https://api.stlouisfed.org/"
        "fred/releases/dates?"
        + params
    )

    with urllib.request.urlopen(
        url,
        timeout=30
    ) as response:

        data = json.loads(
            response.read().decode("utf-8")
        )

    release_dates = data.get(
        "release_dates",
        []
    )

    count = 0
    seen = set()

    for item in release_dates:

        try:
            release_id = int(
                item.get("release_id")
            )
        except (TypeError, ValueError):
            continue

        if release_id not in FRED_RELEASES:
            continue

        event_date = item.get("date")

        if not event_date:
            continue

        # 避免同一个 Release / 日期重复
        key = (
            release_id,
            event_date
        )

        if key in seen:
            continue

        seen.add(key)

        info = FRED_RELEASES[
            release_id
        ]

        events.append({
            "date": event_date,
            "category": "macro",
            "importance": info["importance"],
            "title": info["title"],
            "fullName": info["fullName"],
            "releaseId": release_id,
            "source": "FRED"
        })

        count += 1

    print(
        f"✅ FRED：找到 {count} 个重要宏观事件"
    )


# ==================================================
# 3. FEDERAL RESERVE
# FOMC 官方会议
# ==================================================

FED_URL = (
    "https://www.federalreserve.gov/"
    "monetarypolicy/fomccalendars.htm"
)


MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12
}


def fetch_fomc():

    print()
    print("🏦 正在读取 Federal Reserve FOMC 日历...")

    request = urllib.request.Request(
        FED_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        html = response.read().decode(
            "utf-8",
            errors="ignore"
        )

    start_marker = (
        f"{CURRENT_YEAR} FOMC Meetings"
    )

    start = html.find(start_marker)

    if start == -1:

        print(
            f"⚠️ 没找到 "
            f"{CURRENT_YEAR} FOMC Meetings"
        )

        return

    next_panel = html.find(
        '<div class="panel panel-default">',
        start + len(start_marker)
    )

    if next_panel == -1:
        year_html = html[start:]

    else:
        year_html = html[
            start:next_panel
        ]

    meeting_pattern = re.compile(
        r'<div[^>]*class="[^"]*'
        r'fomc-meeting[^"]*"[^>]*>'
        r'.*?'
        r'fomc-meeting__month[^>]*>'
        r'<strong>([^<]+)</strong>'
        r'.*?'
        r'fomc-meeting__date[^>]*>'
        r'([^<]+)</div>',
        re.DOTALL | re.IGNORECASE
    )

    matches = meeting_pattern.findall(
        year_html
    )

    count = 0

    for month_name, raw_dates in matches:

        month_name = month_name.strip()
        raw_dates = raw_dates.strip()

        if month_name not in MONTHS:
            continue

        month = MONTHS[
            month_name
        ]

        has_sep = "*" in raw_dates

        clean_dates = (
            raw_dates
            .replace("*", "")
            .strip()
        )

        if "-" in clean_dates:

            first_text, second_text = (
                clean_dates.split("-", 1)
            )

            first_day = int(
                first_text.strip()
            )

            second_day = int(
                second_text.strip()
            )

        else:

            first_day = int(
                clean_dates
            )

            second_day = first_day

        day1 = date(
            CURRENT_YEAR,
            month,
            first_day
        )

        day2 = date(
            CURRENT_YEAR,
            month,
            second_day
        )

        # 已经结束的会议跳过
        if day2 < TODAY:
            continue

        # ------------------------------------------
        # FOMC Day 1
        # ------------------------------------------

        events.append({
            "date": day1.isoformat(),
            "category": "fed",
            "importance": "high",
            "title": "FOMC Meeting — Day 1",
            "source": "Federal Reserve"
        })

        count += 1

        # ------------------------------------------
        # Rate Decision
        # ------------------------------------------

        events.append({
            "date": day2.isoformat(),
            "category": "fed",
            "importance": "critical",
            "title": "FOMC Rate Decision",
            "source": "Federal Reserve"
        })

        count += 1

        # ------------------------------------------
        # Press Conference
        # ------------------------------------------

        events.append({
            "date": day2.isoformat(),
            "category": "fed",
            "importance": "critical",
            "title": "Fed Chair Press Conference",
            "source": "Federal Reserve"
        })

        count += 1

        # ------------------------------------------
        # SEP
        # ------------------------------------------

        if has_sep:

            events.append({
                "date": day2.isoformat(),
                "category": "fed",
                "importance": "critical",
                "title": (
                    "Summary of Economic "
                    "Projections (SEP)"
                ),
                "source": "Federal Reserve"
            })

            count += 1

    print(
        f"✅ FOMC：找到 {count} 个未来事件"
    )


# ==================================================
# 执行三个数据源
# ==================================================

try:
    fetch_earnings()

except Exception as e:
    print("❌ 财报读取失败：", e)


try:
    fetch_fred()

except Exception as e:
    print("❌ FRED 读取失败：", e)


try:
    fetch_fomc()

except Exception as e:
    print("❌ FOMC 读取失败：", e)


# ==================================================
# 删除已经过去的事件
# ==================================================

future_events = []

for event in events:

    try:

        event_date = datetime.strptime(
            event["date"],
            "%Y-%m-%d"
        ).date()

    except Exception:
        continue

    if event_date >= TODAY:
        future_events.append(
            event
        )


# ==================================================
# 排序
# ==================================================

CATEGORY_ORDER = {
    "fed": 0,
    "macro": 1,
    "earnings": 2
}


future_events.sort(
    key=lambda item: (
        item["date"],
        CATEGORY_ORDER.get(
            item["category"],
            99
        ),
        item["title"]
    )
)


# ==================================================
# 生成 calendar-data.json
# ==================================================

output = {

    "generatedAt": datetime.now().isoformat(
        timespec="seconds"
    ),

    "today": TODAY.isoformat(),

    "eventCount": len(
        future_events
    ),

    "events": future_events
}


OUTPUT_FILE = "calendar-data.json"


with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        output,
        file,
        ensure_ascii=False,
        indent=2
    )


# ==================================================
# 最终结果
# ==================================================

print()
print("=" * 65)
print("🎉 US MARKET CALENDAR 数据生成完成")
print("=" * 65)

print(
    f"总计：{len(future_events)} 个未来事件"
)

print(
    f"文件：{OUTPUT_FILE}"
)

print()

print("最近 15 个事件：")
print()


for event in future_events[:15]:

    category = event[
        "category"
    ]

    if category == "fed":
        icon = "🏦"

    elif category == "macro":
        icon = "📈"

    else:
        icon = "📊"

    print(
        f"{event['date']} | "
        f"{icon} "
        f"{event['title']}"
    )


print()
print("=" * 65)
print("✅ update-calendar.py finished")
print("=" * 65)