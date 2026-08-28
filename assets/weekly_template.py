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


# ── הלמידה: תיקונים של בעל העסק חוזרים לקובץ הדוגמאות ──────────────
#
# האות היחיד שנלקח הוא שורה שבעל העסק **גם סימן וגם שכתב**.
# שורה שאושרה בלי שינוי היא תוצר של הסוכן עצמו — החזרה שלה פנימה
# מלמדת אותו מעצמו, והקול נסחף לאט בלי שאף אחד שם לב.

def harvest_corrections():
    """מחזיר (נוספו, אושרו_בלי_שינוי). לא מפיל את הריצה לעולם."""
    cfg = CONFIG
    if not cfg.get("pipeline_url"):
        return 0, 0
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline import Pipeline
        rows = Pipeline(cfg["pipeline_url"]).approved()
    except Exception as e:
        print(f"⚠️ קריאת הגיליון נכשלה: {e}")
        return 0, 0

    st = state()
    sent = st.get("hooks_sent", {})
    harvested = set(st.get("harvested", []))

    fresh, unchanged = [], 0
    for r in rows:
        link, hook = r.get("link", ""), (r.get("hook") or "").strip()
        if not link or not hook or link in harvested:
            continue
        original = (sent.get(link) or "").strip()
        if not original:
            continue                      # לא אנחנו כתבנו את זה
        if hook == original:
            unchanged += 1
            continue                      # אושר כמו שהוא — לא נכנס
        fresh.append((r.get("type", ""), hook))
        harvested.add(link)

    if not fresh:
        return 0, unchanged

    ex = Path(cfg.get("examples_file") or
              (Path(cfg["content_folder"]) / "דוגמאות-טובות.md"))
    try:
        if not ex.exists():
            ex.parent.mkdir(parents=True, exist_ok=True)
            ex.write_text("# דוגמאות טובות\n\n"
                          "> הצורה נלמדת מכאן. הקול תמיד מקובץ הקול.\n",
                          encoding="utf-8")
        today = datetime.now().strftime("%d.%m.%Y")
        block = "".join(
            f"\n---\n\n<!-- {kind} · שכתבת בעצמך · {today} -->\n{hook}\n"
            for kind, hook in fresh)
        with ex.open("a", encoding="utf-8") as fh:
            fh.write(block)
    except Exception as e:
        print(f"⚠️ הכתיבה לקובץ הדוגמאות נכשלה: {e}")
        return 0, unchanged

    try:
        st["harvested"] = sorted(harvested)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception as e:
        print(f"⚠️ עדכון ה-state נכשל: {e}")   # הדוגמאות כבר נשמרו

    return len(fresh), unchanged


def main():
    added, unchanged = harvest_corrections()
    if added:
        print(f"📎 {added} שורות שכתבת בעצמך נוספו לדוגמאות")
    if unchanged:
        print(f"   ({unchanged} אושרו בלי שינוי — לא נכנסות, כדי שלא ילמד מעצמו)")

    body = build_body()
    if added:
        body += (f"\n\n---\n📎 למדתי מ-{added} שורות ששכתבת השבוע. "
                 "התוכן הבא יהיה קרוב יותר אליך.")
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
