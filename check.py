name: check
on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install playwright requests && playwright install --with-deps chromium
      - run: python check.py
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: debug
          path: debug.*
