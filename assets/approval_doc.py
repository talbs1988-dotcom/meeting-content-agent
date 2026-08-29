#!/usr/bin/env python3
"""מסמך האישור — המקום היחיד שבעל העסק נוגע בו.

הוא פותח מסמך אחד בגוגל דוקס מהנייד, קורא, מתקן טקסט חופשי, ומחליף
את המילה `לא` ב-`כן` על מה שהוא רוצה להפיק. זהו.

**למה גוגל דוקס ולא גיליון ולא קובץ מסונכרן:**

- **גיליון + Apps Script** — שלושה צעדים ידניים בדפדפן. זו נקודת הנשירה
- **קובץ .md בדרייב** — אפליקציית דרייב בנייד **לא יודעת לערוך אותו**.
  באייפון זו תצוגה בלבד, ו"פתח ב-Docs" יוצר מסמך **נפרד** — הסוכן היה
  קורא לנצח את הגרסה הלא-ערוכה
- **תיקייה מסונכרנת** — נשענת על אפליקציית דרייב שרצה. תועד כשל אמיתי
  שנמשך חודשיים בלי שגיאה אחת

הכל עובר במחבר של קלוד לדרייב, שכבר מותקן ועובד גם בהרצה לילית.
**אין מפתח API, אין Apps Script, אין תיקייה מסונכרנת.**

**למה מסמך חדש כל שבוע ולא קבוע:** המחבר יודע ליצור ולקרוא, אבל
`update_file` משנה רק שם ומיקום — לא תוכן. וזה גם עדיף: בעל עסק סוקר
פעם בשבוע, לא כל לילה.
"""

import re
import subprocess
from datetime import datetime
from pathlib import Path

TIMEOUT = 600
YES = {"כן", "כ", "v", "V", "✓", "✔", "✅", "yes", "1", "אישור"}

HEAD = """עודכן: {date}

רוצה שפריט יופק? תמחק את המילה לא ותכתוב כן.
מה שלא נגעת בו לא יופק ולא יעלה שקל.
מותר לשנות את הטקסט עצמו — התיקון שלך הוא מה שיופק, וגם מה שהסוכן ילמד ממנו.

"""

ITEM = """פריט {n}
סוג: {kind}
אישור: לא

הטקסט:
{text}

"""


# ── בנייה ───────────────────────────────────────────────────────────

def compose(items):
    """items: [{'kind','text','link'}] → הטקסט המלא של המסמך."""
    out = HEAD.format(date=datetime.now().strftime("%d.%m.%Y"))
    for i, it in enumerate(items, 1):
        out += ITEM.format(n=i, kind=it.get("kind", ""),
                           text=(it.get("text") or "").strip())
    return out


def _ask(prompt, tools, claude, log):
    tmp = Path("/tmp/content_agent"); tmp.mkdir(exist_ok=True)
    pf = tmp / f"doc_{datetime.now():%Y%m%d%H%M%S%f}.txt"
    pf.write_text(prompt, encoding="utf-8")
    try:
        r = subprocess.run(
            [claude, "-p", f"קרא את {pf} ובצע.", "--allowedTools", tools],
            capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            log(f"  קלוד נכשל: {r.stderr[:200]}")
            return None
        return r.stdout.strip()
    except Exception as e:
        log(f"  קריאה נכשלה: {e.__class__.__name__}")
        return None
    finally:
        try:
            pf.unlink()
        except Exception:
            pass


def publish(items, folder_id=None, claude="claude", log=print):
    """יוצר את המסמך בדרייב. מחזיר (doc_id, link) או (None, None)."""
    if not items:
        return None, None
    body = compose(items)
    name = f"לאישור · {datetime.now():%d.%m.%Y}"
    where = f" בתוך התיקייה עם המזהה {folder_id}" if folder_id else ""
    out = _ask(
        f"צור בגוגל דרייב **מסמך Google Docs**{where} בשם '{name}'.\n"
        "⚠️ חובה mimeType: application/vnd.google-apps.document\n"
        "   קובץ טקסט רגיל לא ניתן לעריכה באפליקציה בנייד, וזו כל המטרה.\n"
        "⚠️ ובלי זה המסמך נוצר ריק. נבדק.\n\n"
        "התוכן חייב להיות **בדיוק** מה שמופיע אחרי הקו למטה — מילה במילה,\n"
        "בלי לתקן, בלי לקצר, בלי להוסיף כותרות ובלי לעצב.\n"
        "החזר שתי שורות בלבד: המזהה, ואז הקישור.\n"
        "---\n" + body,
        "mcp__claude_ai_Google_Drive__create_file", claude, log)
    if not out:
        return None, None
    ids = re.findall(r"[-\w]{25,}", out)
    link = re.search(r"https://docs\.google\.com/[^\s)`\]<>]+", out)
    if not ids:
        log("  לא חזר מזהה מסמך")
        return None, None
    doc_id = ids[0]
    log(f"  📄 מסמך האישור נוצר · {len(items)} פריטים")
    return doc_id, (link.group(0) if link else
                    f"https://docs.google.com/document/d/{doc_id}/edit")


# ── קריאה ───────────────────────────────────────────────────────────

class DocError(Exception):
    """כשל קריאה. **חייב להתפוצץ ולא להחזיר רשימה ריקה** — אחרת
    ניתוק מהמחבר נראה בדיוק כמו 'בעל העסק לא אישר כלום', ואף אחד
    לא יידע שהמסמך בכלל לא נקרא."""


def fetch(doc_id, claude="claude", log=print):
    out = _ask(
        f"קרא את המסמך {doc_id} מגוגל דרייב.\n"
        "החזר את התוכן **בדיוק כמו שהוא**, מילה במילה, בלי הקדמה,\n"
        "בלי סיכום, בלי עיצוב ובלי להוסיף או להוריד שורות.",
        "mcp__claude_ai_Google_Drive__read_file_content", claude, log)
    if not out or "פריט" not in out:
        raise DocError("המסמך לא נקרא. לבדוק שהמחבר לגוגל דרייב מחובר")
    return out


def parse(text):
    """→ [{'n', 'kind', 'approved', 'text'}].

    כל שיבוש מתדרדר לכיוון הבטוח: נמחקה אות מ'אישור' — לא מאושר.
    נמחק 'פריט 3' — הפריט לא מופק. תמיד ברירת מחדל של אי-הוצאה.
    """
    rows, cur, body, in_body = [], None, [], False
    for raw in text.splitlines():
        line = raw.strip().lstrip("\\")          # Docs מוסיף \ לפני תווים מיוחדים
        m = re.match(r"^פריט\s+(\d+)\s*$", line)
        if m:
            if cur:
                cur["text"] = "\n".join(body).strip()
                rows.append(cur)
            cur, body, in_body = {"n": int(m.group(1)), "kind": "",
                                  "approved": False, "text": ""}, [], False
            continue
        if cur is None:
            continue
        if re.match(r"^סוג\s*:", line):
            cur["kind"] = line.split(":", 1)[1].strip()
            continue
        if re.match(r"^אישור\s*:", line):
            tok = line.split(":", 1)[1].strip().split()
            cur["approved"] = bool(tok) and tok[0].strip(".,!") in YES
            continue
        if re.match(r"^הטקסט\s*:?\s*$", line):
            in_body = True
            continue
        if in_body:
            body.append(raw.rstrip())
    if cur:
        cur["text"] = "\n".join(body).strip()
        rows.append(cur)
    return rows


def approved(doc_id, claude="claude", log=print):
    """רק מה שסומן. זורק DocError אם המסמך לא נקרא."""
    rows = parse(fetch(doc_id, claude, log))
    for r in rows:
        # מפתח ייחודי: מסמך + מספר פריט. מונע הפקה כפולה בין ריצות.
        r["key"] = f"{doc_id}#{r['n']}"
    yes = [r for r in rows if r["approved"]]
    log(f"  {len(yes)} מתוך {len(rows)} סומנו")
    return yes
