#!/usr/bin/env python3
"""השאלות שחוזרות — מוצא מה לקוחות שואלים את בעל העסק שוב ושוב.

הרעיון: לקוח שאל שאלה בפגישה, בעל העסק ענה. השאלה היא ההוק,
התשובה היא הקופי, ושאלה שחוזרת היא המסר המרכזי.

**חלוקת העבודה, וזה העיקר:**
הקיבוץ נעשה בקלוד, כי אותה שאלה מנוסחת אחרת בכל פגישה
("כמה זה עולה" מול "מה המחיר") והתאמת מחרוזות לא תתפוס את זה.
**הספירה נעשית בפייתון**, כי מספר שקלוד מחזיר הוא מספר שאי אפשר
לאמת — ומספר מומצא הוא הדבר שהכי מהר שורף אמון.

הרצה עצמאית:
    python3 questions.py <תיקיית-הניתוחים> <קובץ-פלט>
"""

import json
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

SECTION = "## השאלות ששאלו"
OUT_NAME = "השאלות-שחוזרות.md"
TIMEOUT = 900
MIN_TIMES = 2  # שאלה שנשאלה פעם אחת היא לא "חוזרת"


# ── חיתוך: דטרמיניסטי, בלי קלוד ────────────────────────────────────

def _date_of(path):
    """הניתוחים נשמרים כ-YYYY-MM-DD__<שם>__<מספר>.md"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else None


def cut(learned_dir):
    """מכל ניתוח — רק הסעיף של השאלות, מתויג בתאריך.

    חיתוך כותרות טהור: מ-'## השאלות ששאלו' עד ה-'##' הבא.
    זה מצמצם עשרות קבצים ארוכים לכמה מאות שורות.
    """
    pairs = []
    for f in sorted(Path(learned_dir).glob("*.md")):
        date = _date_of(f)
        if not date:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if SECTION not in text:
            continue
        body = text.split(SECTION, 1)[1]
        body = re.split(r"\n#{1,3} ", body, maxsplit=1)[0]
        for line in body.splitlines():
            line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
            line = line.strip('"״"" ')
            if len(line) > 8:
                pairs.append((date, line))
    return pairs


# ── קיבוץ: קריאה אחת לקלוד ─────────────────────────────────────────

PROMPT = """להלן שאלות שלקוחות שאלו בפגישות. כל שורה: תאריך, ואז השאלה.

**המשימה:** קבץ שאלות שמתכוונות לאותו דבר, גם כשהן מנוסחות אחרת.
"כמה זה עולה" ו"מה המחיר" הן אותה שאלה. "איך מתחילים" ו"מה השלב הראשון" — אותה שאלה.

לכל קבוצה החזר:
- `question` — הניסוח הכי טבעי והכי קרוב לאיך שלקוח באמת שואל
- `dates` — כל התאריכים שבהם הקבוצה הופיעה, בדיוק כפי שהם מופיעים למטה

**⭐ המבחן היחיד שקובע:**

> **האם התשובה על השאלה הזו משנה איך הוא חושב, או רק נותנת לו מידע?**

שאלה שהתשובה עליה היא **עובדה** — לא נכנסת.
שאלה שהתשובה עליה הופכת **אמונה** — נכנסת.

**⛔ מה לא נכנס — ובלי זה הרשימה מתמלאת בזבל:**

- **שאלות מסחריות** — "כמה זה עולה?", "מתי מתחילים?", "יש הנחה?",
  "כמה זמן הליווי?", "מה כולל?"
  ⚠️ **אלה הכי חוזרות והכי חסרות ערך.** כל בעל עסק נשאל אותן,
  והתשובה היא מחירון. אין שם תוכן
- **שאלות שיחה** — "את יודעת מה אני מתכוון?", "נכון?", "מה?"
  טיקים של דיבור. חוזרים בכל פגישה, אפס מידע
- **לוגיסטיקה** — "מתי הפגישה הבאה?", "שלחת לי?", "אפשר להקליט?"
- **שאלות שהיועץ שאל את הלקוח** — רק מה שהלקוח שאל
- **שאלות רטוריות** שהשואל ענה עליהן בעצמו מיד

**✅ מה כן נכנס — שאלה שמסגירה אמונה, פחד או טעות בחשיבה:**

- "אני צריך לגייס עוד מישהו לפני שאני מסדר תהליכים?"
  → מסגירה סדר פעולות הפוך. התשובה הופכת אמונה
- "זה יעבוד גם אצלי? יש לי עסק קטן"
  → מסגירה אמונה ש"קטן" זה חיסרון
- "ומה אם העובד יעזוב אחרי שהשקעתי בו?"
  → מסגירה פחד, ומאחוריו הנחה שהידע הולך עם הבן אדם

**שים לב מה משותף להן:** אחרי התשובה, הבן אדם **חושב אחרת**.
זה מה שעושה תוכן. מחירון לא עושה תוכן.

⚠️ **אל תחזיר מספרים ואל תספור.** רק תאריכים. הספירה נעשית במקום אחר.
⚠️ **אל תמציא תאריך שלא מופיע ברשימה.** תאריך כזה יימחק.
⚠️ קבץ רק שאלות שבאמת אותו דבר. עדיף שתי קבוצות נפרדות מקבוצה אחת מרוחה.

החזר **JSON בלבד**, מערך של אובייקטים, בלי טקסט לפני או אחרי:

[{{"question": "כמה זמן זה לוקח?", "dates": ["2026-04-03", "2026-04-12"]}}]

---
השאלות:

{lines}
"""


def _parse_json(raw):
    """קלוד לפעמים עוטף בגדרות קוד או מקדים במשפט. מחלצים את המערך."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
    i, j = raw.find("["), raw.rfind("]")
    if i == -1 or j <= i:
        return None
    try:
        return json.loads(raw[i:j + 1])
    except json.JSONDecodeError:
        return None


def group(pairs, claude="claude", log=print):
    """מחזיר [{'question': str, 'dates': [str]}] — תאריכים מאומתים בלבד."""
    if not pairs:
        return []

    lines = "\n".join(f"{d} | {q}" for d, q in pairs)
    tmp = Path("/tmp/content_agent")
    tmp.mkdir(exist_ok=True)
    pf = tmp / f"questions_{datetime.now():%Y%m%d%H%M%S}.txt"
    pf.write_text(PROMPT.format(lines=lines), encoding="utf-8")

    try:
        r = subprocess.run(
            [claude, "-p", f"קרא את {pf} ובצע. החזר רק JSON.",
             "--allowedTools", "Read"],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if r.returncode != 0:
            log(f"  קיבוץ השאלות נכשל: {r.stderr[:200]}")
            return []
        data = _parse_json(r.stdout)
        if not isinstance(data, list):
            log("  קלוד לא החזיר JSON תקין")
            return []
    except Exception as e:
        log(f"  קיבוץ השאלות נכשל: {e.__class__.__name__}")
        return []
    finally:
        try:
            pf.unlink()
        except Exception:
            pass

    # אימות: רק תאריכים שבאמת היו בקלט נספרים.
    # בלי זה קלוד יכול "לזכור" תאריך ולנפח את המספר.
    real = {d for d, _ in pairs}
    out = []
    dropped = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        dates = [str(d).strip() for d in item.get("dates", []) if str(d).strip()]
        clean = sorted({d for d in dates if d in real})
        dropped += len(set(dates)) - len(clean)
        if q and clean:
            out.append({"question": q, "dates": clean})
    if dropped:
        log(f"  ⚠️ {dropped} תאריכים שלא היו בקלט — נמחקו")
    return out


# ── דוח: הספירה כאן, בפייתון ───────────────────────────────────────

def _he(date):
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        return f"{d.day}.{d.month}"
    except ValueError:
        return date


def render(groups, total_meetings=0):
    groups = sorted(groups, key=lambda g: -len(g["dates"]))
    repeat = [g for g in groups if len(g["dates"]) >= MIN_TIMES]

    head = f"# השאלות שחוזרות אצלך\n\n> נבנה {datetime.now():%d.%m.%Y}"
    if total_meetings:
        head += f" · מתוך {total_meetings} פגישות"
    head += "\n\n"

    if not repeat:
        return head + (
            "עוד לא נמצאה שאלה שחזרה יותר מפעם אחת.\n\n"
            "**זה לא באג.** צריך כמה פגישות לפני שדפוס מתחיל להופיע.\n"
            "עד אז הסוכן כותב לפי המסרים שהגדרת בקובץ הקול.\n"
        )

    body = [head,
            "**ככה זה עובד:** השאלה היא ההוק. התשובה שנתת בפגישה היא הקופי.\n",
            "התאריכים הם לא קישוט — כל אחד מהם הוא פגישה אמיתית.",
            "אפשר לפתוח את הניתוח של אותו יום ולראות את השאלה במילים שנאמרו.\n"]

    for i, g in enumerate(repeat, 1):
        n = len(g["dates"])
        dates = " · ".join(_he(d) for d in g["dates"])
        body.append(f'{i}. **"{g["question"]}"**\n'
                    f'   נשאלה **{n} פעמים** — {dates}\n')

    once = [g for g in groups if len(g["dates"]) == 1]
    if once:
        label = "שאלה אחת שעלתה" if len(once) == 1 else f"{len(once)} שאלות שעלו"
        body.append(f"\n---\n\n<details>\n<summary>ועוד {label} "
                    "פעם אחת</summary>\n")
        body += [f'- "{g["question"]}" — {_he(g["dates"][0])}' for g in once]
        body.append("\n</details>\n")

    return "\n".join(body)


# ── ההרכבה ─────────────────────────────────────────────────────────

def build(learned_dir, out_path, claude="claude", log=print):
    """מחזיר (מספר שאלות חוזרות, נתיב הקובץ). לא זורק לעולם."""
    try:
        pairs = cut(learned_dir)
    except Exception as e:
        log(f"  קריאת הניתוחים נכשלה: {e.__class__.__name__}")
        return 0, None
    if not pairs:
        log("  אין עדיין שאלות בניתוחים")
        return 0, None

    meetings = len({d for d, _ in pairs})
    log(f"  {len(pairs)} שאלות מ-{meetings} פגישות → מקבץ")
    groups = group(pairs, claude, log)
    if not groups:
        return 0, None

    out_path = Path(out_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render(groups, meetings), encoding="utf-8")
    except Exception as e:
        log(f"  כתיבת הקובץ נכשלה: {e.__class__.__name__}")
        return 0, None

    n = sum(1 for g in groups if len(g["dates"]) >= MIN_TIMES)
    log(f"  ✅ {n} שאלות חוזרות → {out_path.name}")
    return n, out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.parent / OUT_NAME
    n, p = build(src, dst)
    sys.exit(0 if p else 1)
