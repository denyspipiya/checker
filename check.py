import os, re, requests
from collections import Counter
from playwright.sync_api import sync_playwright

URL = "https://phlebotomy.bookinglab.co.uk/barnsleyhospital/37001/services"
TOPIC = os.environ["NTFY_TOPIC"]
TARGET = "October 2026"

def is_grey(bg):
    nums = [int(n) for n in re.findall(r"\d+", bg)[:3]]
    if len(nums) < 3:
        return False
    return max(nums) - min(nums) <= 12 and 215 <= sum(nums) / 3 <= 245

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

    # Make sure the calendar is on October 2026
    header = page.get_by_text(re.compile(r"^[A-Z][a-z]+ 20\d\d$")).first
    for _ in range(4):
        if header.inner_text().strip() == TARGET:
            break
        header.locator("xpath=..").locator("button").first.click()
        page.wait_for_timeout(500)
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
earliest_in_oct = bool(m and m.group(2) == "October")

print("Colours seen:", Counter(x["bg"] for x in days))
print("Open days:", open_days, "| earliest heading:", m.group(0) if m else None)

if open_days or earliest_in_oct:
    msg = "October slots open: " + (", ".join(open_days) or m.group(0))
    requests.post(f"https://ntfy.sh/{TOPIC}", data=msg,
                  headers={"Title": "Blood test slot!", "Priority": "high", "Click": URL})
