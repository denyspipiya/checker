import os, re, time, calendar, traceback, requests
from datetime import datetime, timezone
from collections import Counter
from playwright.sync_api import sync_playwright

URL = "https://phlebotomy.bookinglab.co.uk/barnsleyhospital/37001/services"
TOPIC = os.environ["NTFY_TOPIC"]
TARGET = "October 2026"
MAX_DAYS_TO_READ = 8
INTERVAL_SECONDS = 5 * 60       # check every 5 minutes
RUN_SECONDS = 330 * 60          # each run lasts about 5.5 hours
TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\s?(?:[ap]m)?\b", re.I)

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


def read_times(page):
    body = page.inner_text("body")
    m = re.search(r"Available times on ([^\n]+)\n", body)
    if not m:
        return []
    section = body[m.end():]
    cut = section.find("Accessibility statement")
    if cut != -1:
        section = section[:cut]
    times = []
    for x in TIME_RE.findall(section):
        x = x.strip()
        if x not in times:
            times.append(x)
    return times


def notify(title, text, priority="high"):
    r = requests.post(f"https://ntfy.sh/{TOPIC}", data=text.encode("utf-8"),
                      headers={"Title": title, "Priority": priority, "Click": URL})
    print("ntfy response:", r.status_code, flush=True)


def check_once():
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        try:
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
            if len(days) != EXPECTED_DAYS:
                raise RuntimeError("Calendar does not match " + TARGET)

            print("Colours seen:", dict(Counter(x["bg"] for x in days)), flush=True)
            open_idx = [i for i, x in enumerate(days) if not is_grey(x["bg"])]
            print("Open days:", [days[i]["d"] for i in open_idx], flush=True)

            day_btns = page.locator("button").filter(has_text=re.compile(r"^\d{1,2}$"))
            for i in open_idx[:MAX_DAYS_TO_READ]:
                d = days[i]["d"]
                try:
                    btn = day_btns.nth(i)
                    if btn.inner_text().strip() != d:
                        raise RuntimeError("button order mismatch")
                    btn.click()
                    page.wait_for_timeout(1500)
                    results[d] = read_times(page)
                    print(f"Day {d}: times={results[d]}", flush=True)
                except Exception as e:
                    results[d] = None
                    print(f"Day {d}: could not read times ({e})", flush=True)
        finally:
            b.close()

    open_days = [days[i]["d"] for i in open_idx]
    if not open_days:
        print("No open days, no alert sent", flush=True)
        return
    lines = []
    for d in open_days:
        label = datetime(t.year, t.month, int(d)).strftime("%a %d")
        times = results.get(d)
        if times:
            shown = ", ".join(times[:12]) + (f" (+{len(times) - 12} more)" if len(times) > 12 else "")
            lines.append(f"{label}: {shown}")
        elif d in results:
            lines.append(f"{label}: open (times not read)")
        else:
            lines.append(f"{label}: open")
    notify("Blood test slot!", f"{TARGET} slots available:\n" + "\n".join(lines))


print("SCRIPT VERSION: v8 loop 5min | Target:", TARGET, flush=True)
start = time.time()
n = 0
fails = 0
while True:
    n += 1
    print(f"--- check #{n} at {datetime.now(timezone.utc):%H:%M:%S} UTC ---", flush=True)
    try:
        check_once()
        fails = 0
    except Exception:
        traceback.print_exc()
        fails += 1
        if fails == 3:
            try:
                notify("Checker problem", "The blood test checker failed 3 times in a row.", "default")
            except Exception:
                pass
    if time.time() - start + INTERVAL_SECONDS > RUN_SECONDS:
        break
    time.sleep(INTERVAL_SECONDS)
print("Run finished, next run takes over", flush=True)
