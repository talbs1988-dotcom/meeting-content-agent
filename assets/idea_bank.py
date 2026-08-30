#!/usr/bin/env python3
"""בנק הרעיונות — הקובץ היחיד שבעל העסק פותח.

לפני זה הוא קיבל שני מסמכי ניתוח בשתי תיקיות, ולא ידע מה לעשות איתם.
עכשיו יש קובץ אחד, והוא נקרא בשם של מה שהוא באמת: רעיונות לתוכן.

**מה בפנים, בסדר הזה:**
  1. הרעיונות — ממוספרים, כל אחד עם הציטוט המוכן שלו
  2. מה שהלקוחות אמרו — כאבים, ציטוטים, שאלות
  3. מה שאתה אמרת — הציטוטים והסיפורים שלך
  4. מה באמת קרה בשיחה — מתוך ניתוח המראה

הרעיונות ראשונים בכוונה. **זה מה שהוא בא בשבילו.**
"""

import re
from datetime import datetime
from pathlib import Path


def _section(text, title, stop=r"^#{1,3} "):
    """מחלץ סעיף לפי כותרת, עד הכותרת הבאה."""
    m = re.search(rf"^#{{1,3}} *{re.escape(title)}.*?$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(stop, rest, re.M)
    return (rest[:nxt.start()] if nxt else rest).strip()


def _find(text, *titles):
    for t in titles:
        s = _section(text, t)
        if s:
            return s
    return ""


def build(analysis, mirror="", meeting_name="", date=""):
    """מחזיר את הטקסט של בנק הרעיונות."""
    date = date or datetime.now().strftime("%d.%m.%Y")
    out = [f"# בנק רעיונות · {date}"]
    if meeting_name:
        out.append(f"\n> מתוך: {meeting_name}")

    # ── 1. הרעיונות ──
    # ⚠️ עוצרים על ## בלבד. סעיף הרעיונות מכיל תת-כותרות ### לכל זווית,
    # ובחיתוך על ### הוא היה יוצא ריק — וזה בדיוק החלק שבאים בשבילו.
    ideas = ""
    for title in ("4 זוויות אפשריות לתוכן", "זוויות אפשריות לתוכן",
                  "זוויות לתוכן"):
        ideas = _section(analysis, title, stop=r"^## ")
        if ideas:
            break
    out.append("\n---\n\n## ⭐ הרעיונות\n")
    if ideas:
        out.append("**בוחרים אחד, ואומרים לקלוד: *תעשה מרעיון 2 סרטון*.**\n")
        out.append(ideas)
    else:
        out.append("_לא נמצאו זוויות בניתוח._")

    # ── 2. מה שהלקוח אמר ──
    out.append("\n---\n\n## מה שהלקוחות אמרו\n")
    for label, keys in [
        ("### הכאבים", ("הכאבים שעלו", "הכאבים")),
        ("### השאלות ששאלו", ("השאלות ששאלו",)),
        ("### ציטוטים שלהם", ("ציטוטי זהב של הלקוח (verbatim, בלי מקור)",
                              "ציטוטי זהב של הלקוח")),
        ("### איך הם מנסחים את זה", ("איך הם מנסחים את זה — מילים וביטויים",
                                     "איך הם מנסחים את זה")),
    ]:
        s = _find(analysis, *keys)
        if s:
            out.append(f"{label}\n\n{s}\n")

    # ── 3. מה שאתה אמרת ──
    out.append("\n---\n\n## מה שאתה אמרת\n")
    for label, keys in [
        ("### הציטוטים שלך", ("ציטוטי זהב של בעל העסק (verbatim)",
                              "ציטוטי זהב של בעל העסק")),
        ("### הסיפורים שלך", ("⭐ סיפורים ודוגמאות אישיות שבעל העסק סיפר",
                              "סיפורים ודוגמאות אישיות שבעל העסק סיפר",
                              "סיפורים ודוגמאות אישיות")),
    ]:
        s = _find(analysis, *keys)
        if s:
            out.append(f"{label}\n\n{s}\n")

    # ── 4. מה קרה בשיחה ──
    if mirror.strip():
        out.append("\n---\n\n## מה באמת קרה בשיחה\n")
        for keys in [("שלב 8 — סיכום מראה", "סיכום מראה"),
                     ("שלב 2 — שכבות גלויה וסמויה", "שכבות גלויה וסמויה"),
                     ("שלב 6 — תובנות עומק", "תובנות עומק")]:
            s = _find(mirror, *keys)
            if s:
                out.append(s + "\n")
        out.append("\n_הניתוח המלא בתיקיית `_מראה/`._")

    return "\n".join(out)


def write(analysis, mirror, out_dir, meeting_name="", date=""):
    """כותב את הקובץ. מחזיר את הנתיב, או None."""
    try:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w֐-׿-]+", "-", meeting_name)[:40] or "פגישה"
        p = d / f"{date or datetime.now():%Y-%m-%d}__{stem}.md" \
            if isinstance(date, str) and date else d / f"{stem}.md"
        p.write_text(build(analysis, mirror, meeting_name, date),
                     encoding="utf-8")
        return p
    except Exception:
        return None
