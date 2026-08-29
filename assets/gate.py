#!/usr/bin/env python3
"""שער האישור — הוי בגיליון הוא מה שמפעיל את היוצר.

**הכלל שמחזיק את הכל: ברירת המחדל היא תמיד אי-הוצאה.**
שכח, לא פתח, לא סימן — לא נוצר כלום ולא עלה שקל. הקובץ נשאר לנצח.

הזרימה:
    בעל העסק מסמן וי בגיליון
        ↓  הריצה הלילית קוראת מה סומן
        ↓  לוקחת את הטקסט — כולל התיקונים שלו
        ↓  מפעילה את היוצר, רק על מה שסומן
        ↓  מסמנת שהופק, כדי שלא יופק פעמיים

שתי ההגנות:
  1. **תקרה שבועית קשיחה בקוד.** ההגנה היחידה שלא תלויה בבן אדם
     שזוכר לא לסמן יותר מדי.
  2. **סימון 'הופק' ב-state.** בלי זה אותה שורה מופקת כל לילה מחדש,
     ושורפת קרדיטים בשקט עד שמישהו שם לב לחשבון.
"""

import subprocess
from datetime import datetime
from pathlib import Path

DEFAULT_CAP = 3
TIMEOUT = 1800  # יצירת תמונה, הנפשה ורינדור לוקחים זמן


def _week(when=None):
    d = when or datetime.now()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def pending(pipeline, state, log=print):
    """מה אושר, עוד לא הופק, ובתוך התקרה. מחזיר רשימת שורות."""
    try:
        rows = pipeline.approved()
    except Exception as e:
        log(f"  קריאת הגיליון נכשלה: {e.__class__.__name__}")
        return []

    done = set(state.get("produced", []))
    fresh = [r for r in rows if r.get("link") and r["link"] not in done]
    if not fresh:
        return []

    cap = int(state.get("weekly_cap") or DEFAULT_CAP)
    used = int(state.get("produced_week", {}).get(_week(), 0))
    room = max(0, cap - used)

    if room == 0:
        log(f"  ⛔ הגעת לתקרה השבועית ({cap}). {len(fresh)} מחכים לשבוע הבא")
        return []
    if len(fresh) > room:
        log(f"  ℹ️ {len(fresh)} מסומנים, התקרה מרשה {room} השבוע. "
            f"{len(fresh) - room} נשארים מסומנים")
    return fresh[:room]


def produce(row, producer_cmd, log=print):
    """מפעיל את היוצר על שורה אחת. מחזיר True רק אם הוא באמת הצליח.

    ⚠️ 'הפקודה הצליחה' זה לא 'הסרטון קיים'. קוד יציאה 0 מיוצר גם
    כשהיוצר החזיר הודעה מנומסת ולא ייצר כלום — לכן בודקים פלט.
    """
    if not producer_cmd:
        return None  # אין יוצר מוגדר. זה לא כישלון, זה מצב

    cmd = [c.replace("{hook}", row.get("hook", ""))
            .replace("{link}", row.get("link", ""))
            .replace("{type}", row.get("type", ""))
           for c in producer_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        log(f"  ❌ היוצר נתקע (מעל {TIMEOUT // 60} דקות)")
        return False
    except Exception as e:
        log(f"  ❌ היוצר נכשל: {e.__class__.__name__}")
        return False

    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        log(f"  ❌ היוצר נכשל: {out.strip()[:200]}")
        return False
    # דגל אדום: קוד יציאה 0 עם הודעת כישלון בתוך הפלט
    for sign in ("לא הצלחתי", "אין קרדיטים", "נגמרו הקרדיטים",
                 "אין לי גישה", "צריך לאשר", "ERROR:", "failed"):
        if sign in out:
            log(f"  ❌ היוצר החזיר הצלחה אבל אמר: {sign}")
            return False
    return True


def run(pipeline, state, producer_cmd=None, log=print):
    """מחזיר (הופקו, נכשלו). לא זורק לעולם."""
    if pipeline is None:
        return 0, 0

    rows = pending(pipeline, state, log)
    if not rows:
        return 0, 0

    if not producer_cmd:
        log(f"  ℹ️ {len(rows)} מסומנים ומחכים, אבל אין יוצר מוגדר "
            "(producer_cmd ב-config). לא הופק כלום")
        return 0, 0

    ok = bad = 0
    for r in rows:
        hook = (r.get("hook") or "")[:50]
        log(f"  מפיק: {hook}…")
        res = produce(r, producer_cmd, log)
        if res:
            ok += 1
            state.setdefault("produced", []).append(r["link"])
            wk = state.setdefault("produced_week", {})
            wk[_week()] = wk.get(_week(), 0) + 1
            log("    ✅ הופק")
        else:
            bad += 1
            # ⚠️ לא מסמנים כהופק. בכוונה — שיישאר מסומן וינסה שוב.
            # אבל גם לא מנסים שוב באותה ריצה: כישלון חוזר שורף קרדיטים.

    log(f"  סיכום השער: {ok} הופקו · {bad} נכשלו")
    return ok, bad
