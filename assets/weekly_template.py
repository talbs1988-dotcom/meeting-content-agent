#!/usr/bin/env python3
"""
המייל השבועי — הרגע היחיד שבו בעל העסק נכנס לתמונה.

הוא לא מקבל תוכן במייל. הוא מקבל שורה אחת ולינק לגיליון.
שם הוא קורא, מתקן, ומסמן וי.

רץ פעם בשבוע, ביום ובשעה שנבחרו בהתקנה.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

EMAIL = CONFIG["email"]
CLAUDE = CONFIG.get("claude_path", "claude")
MAIL_TOOL = CONFIG.get("mail_tool", "mcp__claude_ai_Gmail__send_message")
SHEET_URL = CONFIG.get("sheet_url", "")
STATE = HERE / "state.json"

FAILURE_SIGNS = [
    "לא הצלחתי", "אין לי גישה", "צריך לאשר", "לא ניתן",
    "failed", "permission", "unable", "cannot",
]


def state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def week_stats():
    """כמה נכתב בשבוע האחרון, לפי הסיכומים היומיים"""
    root = Path(CONFIG["content_folder"])
    daily = root / "_סיכום_יומי"
    since = datetime.now() - timedelta(days=7)
    pieces = days = 0
    if daily.exists():
        for f in daily.glob("*.md"):
            try:
                d = datetime.strptime(f.stem, "%Y-%m-%d")
            except ValueError:
                continue
            if d < since:
                continue
            days += 1
            pieces += sum(1 for ln in f.read_text(encoding="utf-8").splitlines()
                          if ln.strip().startswith("- "))
    return pieces, days


def pending():
    """כמה שורות עוד לא סומנו. אם אין גשר — None, ולא מנחשים"""
    if not CONFIG.get("pipeline_url"):
        return None
    try:
        sys.path.insert(0, str(HERE))
        from pipeline import Pipeline
        rows = Pipeline(CONFIG["pipeline_url"]).read()
        return sum(1 for r in rows if not r.get("approved"))
    except Exception as e:
        print(f"⚠️ לא הצלחתי לקרוא מהגיליון: {e}")
        return None


def build_body():
    pieces, days = week_stats()
    waiting = pending()
    last = state().get("last_run", "")

    if pieces == 0:
        lines = [
            "השבוע לא נכתב תוכן חדש.",
            "",
            f"הסוכן רץ ב-{days} מתוך 7 הימים." if days else
            "הסוכן לא רץ השבוע — כנראה המחשב היה כבוי.",
            "",
            "אם היו לך פגישות ובכל זאת אין תוכן, כדאי לבדוק",
            "שהתמלולים באמת נוחתים בתיקייה.",
        ]
    else:
        lines = [
            f"נכתבו לך {pieces} פיסות תוכן השבוע.",
            "",
        ]
        if waiting is not None:
            lines += [f"{waiting} מחכות לאישור שלך בגיליון.", ""]
        lines += [
            "עשר דקות: לסרוק את ההוקים, לפתוח אחד שתפס אותך,",
            "לתקן מה שצריך, ולסמן וי.",
            "",
        ]
        if SHEET_URL:
            lines += ["👈 הגיליון שלך:", SHEET_URL, ""]

    lines += [
        "—",
        f"ריצה אחרונה: {last[:16].replace('T', ' ') if last else 'לא ידוע'}",
    ]
    return "\n".join(lines)


def send(subject, body):
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

    # קוד יציאה 0 לא מוכיח שהמייל יצא. קוראים מה שקלוד ענה.
    answer = (r.stdout or "").strip()
    low = answer.lower()
    for sign in FAILURE_SIGNS:
        if sign.lower() in low:
            print(f"❌ המייל לא יצא. קלוד ענה: {answer[:180]}")
            return False

    print(f"✅ נשלח ({answer[:80]})")
    return True


def main():
    body = build_body()
    pieces, _ = week_stats()
    subject = (f"{pieces} תכנים מחכים לך" if pieces else "הסוכן לא כתב השבוע")
    print(body)
    print("-" * 40)
    if "--dry" in sys.argv:
        print("(מצב יבש — לא נשלח)")
        return
    ok = send(subject, body)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
