#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הדופק — רץ בבוקר, בודק שהסוכן עבד, ושולח את המייל.

למה זו תוכנית נפרדת ולא חלק מהסוכן: סוכן שקרס לא יכול לשלוח מייל שהוא
קרס. וגרוע מזה — אם המחשב היה כבוי בשעת הריצה, הסוכן לא קם בכלל, אז אין
קריסה ואין התראה. שקט מוחלט שנראה בדיוק כמו הצלחה.

זה לא תיאורטי: סוכן אמיתי רץ ככה 24 לילות ברצף בלי לייצר כלום, ואיש
לא ידע.

הדופק שואל שאלה אחת — "נחת אתמול קובץ?" — ולא אכפת לו למה לא.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
CONTENT_ROOT = Path(CONFIG["content_folder"])
FOLDERS = ["רילס", "קרוסלה", "פוסט", "סטורי"]
DAILY_SUMMARY = CONTENT_ROOT / "_סיכום_יומי"
LEARNED = CONTENT_ROOT / "_מה_למדנו"
LOGS = HERE / "logs"
EMAIL = CONFIG["email"]
CLAUDE = CONFIG.get("claude_path", "claude")


def todays_output():
    """מה נוצר היום. מחזיר (רשימת קבצים, האם הסוכן רץ בכלל)."""
    today = datetime.now().strftime("%Y-%m-%d")
    found = []
    for name in FOLDERS:
        d = CONTENT_ROOT / name
        if d.exists():
            found += [f for f in d.glob(f"{today}_*.md")]
    if found:
        return found, True
    # אין תוכן — אבל אולי הסוכן כן רץ ולא היו פגישות
    summary = DAILY_SUMMARY / f"{today}.md"
    if summary.exists():
        age = datetime.now() - datetime.fromtimestamp(summary.stat().st_mtime)
        if age < timedelta(hours=20):
            return [], True
    return [], False


def meetings_count():
    """כמה פגישות עובדו — נקרא מהסיכום היומי שהסוכן כתב."""
    today = datetime.now().strftime("%Y-%m-%d")
    f = DAILY_SUMMARY / f"{today}.md"
    if f.exists():
        m = re.search(r"נותחו (\d+) פגישות", f.read_text(encoding="utf-8", errors="ignore"))
        if m:
            k = int(m.group(1))
            return "פגישה אחת" if k == 1 else f"{k} פגישות"
    return "הפגישות שלך"


def recent_log():
    logs = sorted(LOGS.glob("*.log"))
    if not logs:
        return "אין לוגים בכלל"
    tail = logs[-1].read_text(encoding="utf-8", errors="ignore").strip().split("\n")
    return "\n".join(tail[-15:])


# ביטויים שמעידים שהמייל לא באמת יצא, למרות קוד יציאה 0
FAILURE_SIGNS = [
    "צריך לאשר", "צריך אישור", "אין לי גישה", "לא הצלחתי",
    "לא ניתן", "אין הרשאה", "permission", "not authorized",
    "unable to", "i cannot", "failed",
]

MAIL_TOOL = "mcp__claude_ai_Gmail__send_message"


def send(subject, body):
    """שולח דרך חיבור המייל של בעל העסק שכבר קיים בקלוד קוד.

    מהחשבון שלו, לכתובת שלו. אין חשבון מרכזי ואין מפתחות להעתיק.

    ⚠️ שתי מלכודות שנתפסו בבדיקה אמיתית:

    1. בלי --allowedTools, קלוד בהרצה אוטומטית מבקש אישור אינטראקטיבי
       שאין מי שייתן אותו בשתיים בלילה. הוא מחזיר תשובה מנומסת
       ("צריך לאשר את ההרשאה") **וקוד יציאה 0**.

    2. ולכן קוד יציאה 0 לא מוכיח כלום. צריך לקרוא את מה שהוא ענה.
       זה בדיוק המסך הירוק שמשקר, והוא נתפס כאן רק כי בדקנו בתיבה
       אחרי שהקוד אמר "נשלח".
    """
    prompt = (
        f"שלח מייל אל {EMAIL}\n"
        f"נושא: {subject}\n\n"
        f"גוף ההודעה (שלח אותו כמו שהוא, בלי לשנות מילה):\n\n{body}"
    )
    try:
        r = subprocess.run(
            [CLAUDE, "-p", prompt, "--allowedTools", MAIL_TOOL],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        print(f"❌ השליחה קרסה: {e}")
        return False

    if r.returncode != 0:
        print(f"❌ השליחה נכשלה (קוד {r.returncode}): {r.stderr[:200]}")
        return False

    answer = (r.stdout or "").strip()
    low = answer.lower()
    for sign in FAILURE_SIGNS:
        if sign.lower() in low:
            print(f"❌ המייל לא יצא. קלוד ענה: {answer[:180]}")
            return False

    print(f"✅ נשלח ({answer[:80]})")
    return True


def main():
    files, ran = todays_output()

    if not ran:
        # זה התרחיש שהדופק נבנה בשבילו.
        # מבדילים בין "לא קם בכלל" (מחשב כבוי) ל"קם ונפל" — זה משנה
        # לגמרי מה בעל העסק צריך לעשות.
        crash = LOGS / "last_failure.txt"
        crashed_today = (
            crash.exists()
            and (datetime.now() - datetime.fromtimestamp(crash.stat().st_mtime)) < timedelta(hours=20)
        )
        if crashed_today:
            detail = crash.read_text(encoding="utf-8", errors="ignore")[:400]
            send(
                "⚠️ הסוכן נתקל בבעיה",
                f"""הסוכן קם אתמול אבל נתקל בבעיה ולא הצליח לסיים.

מה זה אומר: לא נוצר תוכן חדש.

מה לעשות: תגיד לקלוד "הסוכן שלי לא רץ, תבדוק".

---
{detail}""",
            )
            return
        send(
            "⚠️ הסוכן לא רץ אתמול",
            f"""לא נוצר תוכן חדש אתמול, ולא נראה שהסוכן רץ בכלל.

מה זה אומר: אין תוכן חדש היום.

מה לעשות: תגיד לקלוד "הסוכן שלי לא רץ, תבדוק".
אם המחשב היה כבוי בלילה — זו כנראה הסיבה, ומחר זה יסתדר לבד.

---
מה שמופיע בלוג האחרון:
{recent_log()}""",
        )
        return

    if not files:
        send(
            "אין תוכן חדש היום",
            """לא היו פגישות חדשות מאתמול, אז אין חומר חדש לעבוד איתו.

הכל תקין — הסוכן בדק וימשיך לעקוב.""",
        )
        return

    # המייל הוא סטטוס בלבד. לא תוכן, לא מסקנות, לא תובנות.
    # בעל העסק צריך לדעת דבר אחד: הסוכן רץ, וכמה מחכה לו. הכל
    # מחכה בתיקייה, והוא נכנס אליה כשנוח לו.
    n = len(files)
    by_kind = {}
    for f in files:
        by_kind[f.parent.name] = by_kind.get(f.parent.name, 0) + 1

    hour = CONFIG.get("run_hour", 21)
    piece = "פיסת תוכן אחת" if n == 1 else f"{n} פיסות תוכן"
    verb = "מחכה" if n == 1 else "מחכות"

    lines = [
        f"הסוכן רץ אתמול ב-{hour}:00",
        "",
        f"{meetings_count()} → {piece}",
        "",
    ]
    for kind, c in by_kind.items():
        lines.append(f"   {kind}: {c}")

    drive_link = CONFIG.get("drive_link", "").strip()
    lines += ["", f"📁 {verb} לך בתיקייה:"]
    lines.append(drive_link if drive_link else f"   {CONTENT_ROOT.name}")
    lines.append("")

    subject = f"הסוכן רץ · {piece} {verb} לך"
    send(subject, "\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"הדופק עצמו נכשל: {e}\n{traceback.format_exc()}")
        try:
            send("⚠️ תקלה במערכת התוכן",
                 f"הדופק עצמו נתקל בבעיה.\n\nתגיד לקלוד: \"הסוכן שלי לא רץ, תבדוק\".\n\n{e}")
        except Exception:
            pass
        sys.exit(1)
