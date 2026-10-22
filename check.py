import os, re, requests
from datetime import datetime
from collections import Counter
from playwright.sync_api import sync_playwright

URL = "https://phlebotomy.bookinglab.co.uk/barnsleyhospital/37001/services"
TOPIC = os.environ["NTFY_TOPIC"]
TARGET = "November 2026"   # change back to "October 2026" after testing

def is_grey(bg):
    nums = [int(n) for n in re.findall(r"\d+", bg)[:3]]
    if len(nums) < 3:
        return False
    return max(nums) - min(nums) <= 12 and 215 <= sum(nums) / 3 <= 245

def month_index(text):
    d = datetime.strptime(text.strip(), "%B %Y")
    return d.year * 12 + d.month

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 420, "height": 900})
    page.goto(URL, wait_until="networkidle")
    try:
        page.get_by_label("Yes").check()
    except Exception:
        pass
    page.get_by_role("link", name=re.compile("Phlebotomy Booking Service", re.I)).click()
    page.get_by_role("link", name=re.compile("Community Diagnostic Centre", re.I)).first.click()
    page.get_by_text("Select a date and time").wait_for()
    page.wait_for_timeout(1500)

    # Move the calendar to the target month
    header = page.get_by_text(re.compile(r"^[A-Z][a-z]+ 20\d\d$")).first
    row = header.locator("xpath=ancestor::*[.//button][1]")
    arrows = row.locator("button").filter(has_not_text=re.compile(r"^\d{1,2}$"))
    for _ in range(6):
        current = header.inner_text().strip()
        if current == TARGET:
            break
        if month_index(current) < month_index(TARGET):
            arrows.last.click()    # next month
        else:
            arrows.first.click()   # previous month
        page.wait_for_timeout(700)
    if header.inner_text().strip() != TARGET:
        raise RuntimeError("Could not reach " + TARGET)

    days = page.evaluate(r"""() => [...document.querySelectorAll('button')]
      .filter(x => /^\d{1,2}$/.test(x.innerText.trim()))
      .map(x => ({d: x.innerText.trim(), bg: getComputedStyle(x).backgroundColor}))""")
    if not days:
        raise RuntimeError("No day buttons found")

    body = page.inner_text("body")
    page.screenshot(path="debug.png", full_page=True)
    open("debug.html", "w").write(page.content())
    b.close()

open_days = [x["d"] for x in days if not is_grey(x["bg"])]
m = re.search(r"Available times on \w+ (\d{1,2}) (\w+) (\d{4})", body)
earliest_in_target = bool(m and m.group(2) == TARGET.split()[0])

print("Target:", TARGET)
print("Colours seen:", Counter(x["bg"] for x in days))
print("Open days:", open_days, "| earliest heading:", m.group(0) if m else None)

if open_days or earliest_in_target:
    msg = f"{TARGET} slots open: " + (", ".join(open_days) or m.group(0))
    requests.post(f"https://ntfy.sh/{TOPIC}", data=msg,
                  headers={"Title": "Blood test slot!", "Priority": "high", "Click": URL})
