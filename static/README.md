# static/

Place your `index.html` here, then run the patch script from the repo root:

```bash
python apply_practice_day_patch.py static/index.html
```

The script will:
1. Back up your existing file to `static/index.html.bak`
2. Apply all practice day changes
3. Report each patch step (✓ applied / ✗ not found)

## What the patch adds

- PDF parsing for `Practice Match` blocks (all regional format variants)
- Practice Day UI panel (collapsed by default, above Daily Schedule)
- `▶ Practice Day` checkbox with time, guaranteed matches, filler, and cycle time fields
- `PDF ✓` badge when practice time was auto-loaded from the event agenda
- Practice matches rendered as P1, P2… before qualification Day 1
- Qual stats exclude practice matches
- URL persistence: `?pday=1&pd=08:00-17:00&pmpt=3&pfill=99&pct=9`
- DB `day_config` persistence under `practiceDay` key
- CSV export `Type` column: `Practice` / `Qualification`
