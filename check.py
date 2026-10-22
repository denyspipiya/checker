import os, re, calendar, requests
from datetime import datetime
from collections import Counter
from playwright.sync_api import sync_playwright

URL = "https://phlebotomy.bookinglab.co.uk/barnsleyhospital/37001/services"
TOPIC = os.environ["NTFY_TOPIC"]
TARGET = "October 2026"

t = datetime.strptime(TARGET, "%B %Y")
EXPECTED_DAYS = calendar.monthrange(t.year, t.month)[1]


def is_grey(bg):
    nums = [int(n) for n in re.findall(r"\d+", bg)[:3]]
    if len(nums) < 3:
        return False
    return max(nums) - min(nums) <= 12 and 215 <= sum(nums) / 3 <= 245


def month_index(text):
    d = datetime.strptime(text.strip(), "%B %Y")
    return d.year * 12 + d.month


print("SCRIPT VERSION: v4 | Target:", TARGET)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    page = b.new_page(viewport={"width": 420, "height": 900})
    page.set_default_timeout(30000)
    page.goto(URL, wait_until="networkidle")
    try:
        page.get_by_label("Yes").check()
    except Exception:
        pass
    page.get_by_role("link", name=re.compile("Phlebotomy Booking Service", re.I)).click()
    page.get_by_role("link", name=re.compile("Community Diagnostic Centre", re.I)).first.click()
    page.get_by_text("Select a date and time").wait_for()
    page.wait_for_timeout(1500)

    header = page.get_by_text(re.compile(r"^[A-Z][a-z]+ 20\d\d$")).first
    row = header.locator("xpath=ancestor::*[.//button][1]")
    arrows = row.locator("button").filter(has_not_text=re.compile(r"^\d{1,2}$"))
    for _ in range(6):
        current = header.inner_text().strip()
        if current == TARGET:
            break
        if month_index(current) < month_index(TARGET):
            arrows.last.click()
        else:
            arrows.first.click()
        page.wait_for_timeout(1000)
    print("Calendar header shows:", header.inner_text().strip())
    if header.inner_text().strip() != TARGET:
        raise RuntimeError("Could not reach " + TARGET)

    days = []
    for _ in range(10):
        days = page.evaluate(r"""() => [...document.querySelectorAll('button')]
          .filter(x => /^\d{1,2}$/.test(x.innerText.trim()))
          .map(x => ({d: x.innerText.trim(), bg: getComputedStyle(x).backgroundColor}))""")
        if len(days) == EXPECTED_DAYS:
            break
        page.wait_for_timeout(500)
    print("Day buttons found:", len(days), "| expected:", EXPECTED_DAYS)
    if len(days) != EXPECTED_DAYS:
        raise RuntimeError("Calendar does not match " + TARGET)
    b.close()

open_days = [x["d"] for x in days if not is_grey(x["bg"])]
print("Colours seen:", Counter(x["bg"] for x in days))
print("Open days:", open_days)

if open_days:
    msg = f"{TARGET} slots open on: " + ", ".join(open_days)
    r = requests.post(f"https://ntfy.sh/{TOPIC}", data=msg,
                      headers={"Title": "Blood test slot!", "Priority": "high", "Click": URL})
    print("ntfy response:", r.status_code)
else:
    print("No open days, no alert sent")
