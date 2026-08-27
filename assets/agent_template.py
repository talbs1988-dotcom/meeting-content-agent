#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""סוכן התוכן — הריצה הלילית.

התבנית הזו מגיעה מסוכן שרץ בעסק חי ונשבר ב-14 דרכים שונות. כל הגנה כאן
מתקנת כשל אמיתי, ומי שעורך אותה כדאי שיקרא קודם את references/reliability.md.

שימוש:
    python3 agent.py           ריצה מלאה
    python3 agent.py --test    קובץ אחד, פלט אחד, בלי לעדכן מצב
"""
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# מבנה התיקיות מועתק מסוכן שרץ בעסק חי חודשים, לא הומצא כאן.
# תוכן מסודר לפי סוג — "תביא לי קרוסלה" זה מקום אחד. התאריך בשם הקובץ.
# הכל בדרייב, כי שם בעל העסק כבר מחפש את הדברים שלו ומשם הוא מגיע
# אליהם גם מהנייד.
CONTENT_ROOT = Path(CONFIG["content_folder"])
FOLDERS = {
    "POV": CONTENT_ROOT / "POV",
    "ריל": CONTENT_ROOT / "רילס",
    "קרוסלה": CONTENT_ROOT / "קרוסלה",
    "פוסט": CONTENT_ROOT / "פוסט",
    "סטורי": CONTENT_ROOT / "סטורי",
}
DAILY_SUMMARY = CONTENT_ROOT / "_סיכום_יומי"
LEARNED = CONTENT_ROOT / "_מה_למדנו"  # מצטבר, לא נמחק — זה הנכס

# המנוע מקומי בכוונה: state.json נכתב תוך כדי ריצה, וקובץ שהסנכרון
# תופס באמצע כתיבה הוא קובץ פגום.
LOGS = HERE / "logs"
STATE_FILE = HERE / "state.json"

TRANSCRIPTS = Path(CONFIG["transcripts_folder"])
VOICE_FILE = Path(CONFIG["voice_file"])
SKILL_REFS = Path(CONFIG["skill_refs"])  # תיקיית references של הסקיל

CLAUDE = CONFIG.get("claude_path", "claude")
CLAUDE_TIMEOUT = 600
LOOKBACK_DAYS = CONFIG.get("lookback_days", 30)
# כמה פורמטים לכל פגישה. 3 פגישות ביום → 9 פיסות תוכן.
# כל פיסה מבוססת על פגישה אחת בלבד, בלי ערבוב — כשמערבבים שתי פגישות
# בפוסט אחד הזווית מתפשרת ואף אחת מהן לא נשמעת אמיתית.
PIECES_PER_MEETING = CONFIG.get("pieces_per_meeting", 3)

READABLE = {".txt", ".md", ".json", ".vtt", ".srt", ".docx"}

FORMATS = {
    # POV הוא פורמט בפני עצמו, לא תת-סוג של פוסט. יש לו חוקי קול
    # משלו (references/pov.md) והוא הפורמט שהכי מהר בונה חיבור.
    "POV": ["POV1", "POV2", "POV3"],
    "פוסט": [f"P{i}" for i in range(1, 11)],
    "ריל": [f"R{i}" for i in range(1, 9)],
    "קרוסלה": [f"C{i}" for i in range(1, 8)],
    "סטורי": [f"S{i}" for i in range(1, 5)],
}

# ── לוג ─────────────────────────────────────────────────────────────

LOG_FILE = None


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def setup_logging():
    global LOG_FILE
    LOGS.mkdir(parents=True, exist_ok=True)
    LOG_FILE = LOGS / f"{datetime.now():%Y-%m-%d}.log"


def safe(fn, *a, **kw):
    """פעולה נלווית שכישלון בה לא צריך להפיל ריצה שלמה.

    למה: chmod ויצירת תיקיות נכשלים כשהסקריפט רץ מהמתזמן ולא מהטרמינל —
    למתזמן אין את אותן הרשאות. זה הפיל סוכן אמיתי 6 פעמים.
    """
    try:
        return fn(*a, **kw)
    except Exception as e:
        log(f"  (פעולה נלווית נכשלה, ממשיך: {e.__class__.__name__})")
        return None


# ── מצב ─────────────────────────────────────────────────────────────


def load_state():
    base = {"last_run": None, "processed_files": [], "format_history": {}}
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            base.update(s)
        except Exception as e:
            log(f"state.json פגום ({e}) — מתחיל מחדש")
    return base


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── קלוד ────────────────────────────────────────────────────────────

JUNK_MARKERS = [
    "מופיע למעלה",
    "כפי שציינתי",
    "כבר השתמשתי",
    "as mentioned above",
    "I have everything I need",
    "Let me produce",
]


def looks_like_junk(text, min_len=800):
    """תופס פלט שהוא מטא-טקסט במקום תוצר.

    מודל מחזיר לפעמים "הניתוח מופיע למעלה" במקום הניתוח. בלי הבדיקה הזו
    זה נשמר, והלוג רושם ✅ על 300 בתים של כלום.
    """
    if not text or len(text.strip()) < min_len:
        return f"קצר מדי ({len(text.strip()) if text else 0} תווים)"
    opening = text.strip()[:400].lower()
    for m in JUNK_MARKERS:
        if m.lower() in opening:
            return f"נפתח במטא-טקסט: {m!r}"
    return None


def strip_preamble(text):
    """חותך מחשבות פנימיות שדלפו לפני התוכן.

    ראינו קופי שנשמר כשהוא פותח ב-"Good - the metaphor is verified".
    זו מחשבה של המודל, לא טקסט לפרסום.
    """
    lines = text.split("\n")
    start = 0
    for i, line in enumerate(lines[:6]):
        st = line.strip()
        if not st:
            continue
        if st.startswith(("#", "**", "##")):
            start = i
            break
        letters = [c for c in st if c.isalpha()]
        if letters and sum(1 for c in letters if "a" <= c.lower() <= "z") / len(letters) > 0.5:
            start = i + 1
    out = "\n".join(lines[start:]).strip(" -\n")
    return out or text.strip()


def ask_claude(prompt, label="claude", min_len=800):
    """שולח לקלוד, מנקה, מאמת, ומנסה שוב פעם אחת."""
    tmp = Path("/tmp/content_agent")
    tmp.mkdir(exist_ok=True)
    pf = tmp / f"{label}_{datetime.now():%Y%m%d%H%M%S%f}.txt"
    pf.write_text(prompt, encoding="utf-8")
    try:
        for attempt in (1, 2):
            # --allowedTools חיוני: בהרצה אוטומטית אין מי שיאשר הרשאה
            # אינטראקטיבית, וקלוד יחזיר תשובה מנומסת עם קוד יציאה 0.
            r = subprocess.run(
                [CLAUDE, "-p", f"קרא את {pf} ובצע. החזר רק את הפלט הסופי.",
                 "--allowedTools", "Read,Glob,Grep"],
                capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
            )
            if r.returncode != 0:
                log(f"  קלוד נכשל (ניסיון {attempt}): {r.stderr[:200]}")
                continue
            out = strip_preamble(r.stdout.strip())
            bad = looks_like_junk(out, min_len)
            if not bad:
                return out
            log(f"  פלט לא תקין ({bad}) — ניסיון {attempt}")
        return None
    finally:
        safe(pf.unlink)


# ── סודיות ──────────────────────────────────────────────────────────


def anonymize(text, known_names=None):
    """מחליף שמות בתוויות ניטרליות, לפני שהתמלול נשלח לניתוח.

    מה שלא נכנס לא יכול לצאת. זו ההגנה הזולה והאמינה ביותר.

    ⚠️ שתי שכבות, ושתיהן נדרשות:

    1. **תוויות דובר** בתחילת שורה ("שם: טקסט").
    2. **שמות בתוך הדיבור עצמו** — "ודניאל בסוף יוני מתפנה". זו הדליפה
       שנתפסה בבדיקה: שם של אדם שלישי הוזכר עשר פעמים בגוף השיחה, עבר
       את הניקוי, והגיע עד למייל של בעל העסק.

    ⚠️ התוויות ניטרליות בכוונה — [דובר 1], לא [בעל העסק].
    ניחוש לפי סדר הדיבור נכשל: בשיחות רבות הלקוח פותח. ניחוש שגוי כאן
    מייחס את הכאבים של הלקוח לבעל העסק, וכל התוכן יוצא הפוך.
    """
    speakers = {}
    pat = re.compile(r"^(?:\[[^\]]+\]\s*)?([A-Za-z֐-׿][\w֐-׿' ]{1,30}):\s")
    for line in text.split("\n"):
        m = pat.match(line.strip())
        if m:
            speakers.setdefault(m.group(1).strip(), None)
    for i, name in enumerate(speakers, 1):
        speakers[name] = f"[דובר {i}]"
    for name, tag in speakers.items():
        text = re.sub(rf"(?<![\w֐-׿]){re.escape(name)}(?![\w֐-׿])", tag, text)

    # שכבה שנייה: כל שם ידוע, בכל מקום בטקסט — כולל חלקי שם.
    # "Daniel Shenhar" צריך לתפוס גם "דניאל" וגם "Daniel" לחוד.
    for full in sorted(known_names or [], key=len, reverse=True):
        parts = [full] + [w for w in full.split() if len(w) > 2]
        for w in sorted(set(parts), key=len, reverse=True):
            text = re.sub(rf"(?<![\w֐-׿]){re.escape(w)}(?![\w֐-׿])", "[הושמט]", text)

    return text


def has_leaked_names(text):
    """שכבה שנייה: שואל את קלוד אם נשאר שם מזהה בפלט.

    למה לא regex: רשימת שמות קבועה תופסת עשרה שמות ומפספסת אלפים, וגם
    לא תתפוס זיהוי עקיף ("הבעלים של הרשת הגדולה בצפון"). הסודיות היא
    הדבר הקריטי ביותר כאן, וזה לא מקום לחסוך בו קריאה אחת.

    מחזיר את מה שנמצא, או None אם נקי.
    """
    check = ask_claude(
        f"""האם בטקסט הבא מופיע שם של אדם, שם של עסק, שם מקום, או פרט
שמאפשר לזהות לקוח מסוים?

ציטוט בלי שם הוא תקין. תיאור כללי ("לקוחה בתחום היופי") תקין.
מה שלא תקין: שם פרטי, שם משפחה, שם עסק, עיר, או צירוף שמזהה אדם ספציפי.

ענה במילה אחת "נקי", או בשם/הפרט שמצאת. בלי הסבר.

---
{text[:6000]}""",
        label="privacy_check",
        min_len=0,
    )
    if not check:
        # אם הבדיקה עצמה נכשלה — לא מניחים שנקי
        log("  ⚠️ בדיקת הסודיות לא רצה — מתייחס כאילו יש חשד")
        return "בדיקה נכשלה"
    # מנקים עיצוב לפני ההשוואה: קלוד עונה לפעמים "**נקי**" עם הדגשה,
    # ובדיקה על המחרוזת הגולמית פוסלת אז טקסט תקין לגמרי.
    # זו מלכודת 6 (הבודק שפוסל עבודה טובה) במסווה חדש.
    ans = re.sub(r"[*_`#\s]+", " ", check).strip()
    return None if ans.startswith("נקי") else ans[:60]


def upload_to_drive(local_path, kind, drive_folder_name):
    """מעלה את הקובץ לגוגל דרייב דרך קלוד, בלי אפליקציית דרייב על המחשב.

    למה לא תיקייה מסונכרנת: זה תלוי באפליקציה שרצה. אצל בעל עסק אמיתי
    האפליקציה נמחקה (תפסה מקום בדיסק), והתוצאה הייתה שחודשיים של תוכן
    ישבו על המחשב ולא הגיעו לענן — **בלי שום שגיאה.** הסוכן דיווח
    "נשמר", והוא באמת נשמר. הוא פשוט לא הגיע ליעד.

    ככה זה לא תלוי בכלום חוץ מהחיבור שכבר קיים בקלוד קוד.
    """
    if not CONFIG.get("upload_to_drive", True):
        return True
    content = local_path.read_text(encoding="utf-8")
    prompt = (
        f"העלה לגוגל דרייב שלי קובץ בשם '{local_path.stem}' "
        f"לתיקייה '{drive_folder_name}' (אם אין תיקייה כזו, צור אותה "
        f"בתוך '{CONTENT_ROOT.name}').\n\n"
        f"התוכן:\n\n{content}"
    )
    try:
        r = subprocess.run(
            [CLAUDE, "-p", prompt, "--allowedTools",
             "mcp__claude_ai_Google_Drive__create_file,mcp__claude_ai_Google_Drive__search_files"],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as e:
        log(f"  ⚠️ ההעלאה לדרייב קרסה: {e.__class__.__name__}")
        return False

    ans = (r.stdout or "").lower()
    if r.returncode != 0 or any(s in ans for s in
                                ["לא הצלחתי", "אין לי גישה", "צריך לאשר", "failed", "permission"]):
        log(f"  ⚠️ ההעלאה לדרייב נכשלה. הקובץ נשמר מקומית: {local_path.name}")
        return False
    log("  ☁️ הועלה לדרייב")
    return True


def save_docx(md_text, out_path, title=None):
    """שומר גם גרסת Word, עם יישור לימין.

    למה: בעל עסק לא טכני עורך ב-Word או ב-Pages, לא בעורך טקסט. הסוכן
    שרץ בעסק חי מייצר את שתי הגרסאות, וזו שנפתחת בפועל היא ה-DOCX.

    נכשל בשקט אם הספרייה לא מותקנת — זה נחמד־שיהיה, לא קריטי, ואסור
    שיפיל ריצה שלמה.
    """
    try:
        from docx import Document
        from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
        from docx.oxml.ns import qn
    except ImportError:
        return False
    try:
        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = "Arial"
        style.element.rPr.rFonts.set(qn("w:cs"), "Arial")
        if title:
            h = doc.add_heading(title, level=1)
            h.alignment = WD_PARAGRAPH_ALIGNMENT.RIGHT
        for raw in md_text.split("\n"):
            line = raw.rstrip()
            if line.startswith("#"):
                lvl = min(len(line) - len(line.lstrip("#")), 4)
                para = doc.add_heading(line.lstrip("# ").strip(), level=lvl)
            else:
                para = doc.add_paragraph(line.lstrip("- ") if line.startswith("- ") else line)
            para.alignment = WD_PARAGRAPH_ALIGNMENT.RIGHT
            para.paragraph_format.right_to_left = True
        doc.save(str(out_path))
        return True
    except Exception as e:
        log(f"  (DOCX נכשל, ה-MD נשמר: {e.__class__.__name__})")
        return False


# ── קריאת קבצים ─────────────────────────────────────────────────────


def read_transcript(path):
    """מוציא טקסט מכל פורמט שכלי תמלול מייצרים.

    מחזיר (טקסט, שמות_ידועים). השמות נאספים מרשימת הדוברים — בקובץ JSON
    הם יושבים בשדה נפרד, ואם לא אוספים אותם משם הם נכנסים לטקסט כמו שהם.
    """
    names = set()
    try:
        if path.suffix == ".json":
            d = json.loads(path.read_text(encoding="utf-8"))
            tr = d.get("transcript", d)
            for s in tr.get("speakers", []):
                n = (s.get("name") or "").strip()
                if n:
                    names.add(n)
            segs = tr.get("segments") or d.get("segments") or []
            if segs:
                text = "\n".join(
                    f"{s.get('speaker_id', s.get('speaker', '?'))}: {s.get('text', '')}"
                    for s in segs
                )
                return text, names
            return json.dumps(d, ensure_ascii=False), names

        if path.suffix == ".docx":
            r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)],
                               capture_output=True, text=True, timeout=60)
            return r.stdout, names

        if path.suffix in {".vtt", ".srt"}:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            keep = [l for l in raw.split("\n")
                    if l.strip() and "-->" not in l and not l.strip().isdigit()
                    and l.strip() != "WEBVTT"]
            return "\n".join(keep), names

        return path.read_text(encoding="utf-8", errors="ignore"), names
    except Exception as e:
        log(f"  לא הצלחתי לקרוא {path.name}: {e}")
        return None, names


def find_new(state):
    """חלון קבוע אחורה, וסינון לפי מה שכבר טופל.

    לא "מאז הריצה האחרונה": תמלול שהושלם באיחור נעלם אז לתמיד.
    """
    if not TRANSCRIPTS.exists():
        raise RuntimeError(f"תיקיית התמלולים לא קיימת: {TRANSCRIPTS}")
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).timestamp()
    done = set(state["processed_files"])
    out = []
    for f in TRANSCRIPTS.rglob("*"):
        if f.is_file() and f.suffix.lower() in READABLE and f.name not in done:
            if f.stat().st_mtime >= cutoff:
                out.append(f)
    return sorted(out, key=lambda p: p.stat().st_mtime)


# ── רוטציה ──────────────────────────────────────────────────────────


def pick_audience_layer(kind, used_today, layers):
    """כל פיסת תוכן מכוונת לפלח קהל אחר, ומתחלפת ביניהם.

    למה זה חשוב: בלי זה כל התוכן של אותו יום מדבר לאותו אדם, והפיד
    נשמע כמו תקליט שנתקע. הסוכן שרץ בעסק חי עושה את זה מהיום הראשון,
    ובלי זה התוכן נראה חוזר על עצמו גם כשהפורמטים מתחלפים.

    הפלחים מגיעים מקובץ הקול (החלק "למי אני מוכר"). אם אין שם פילוח,
    מחזירים None והתוכן פשוט לא מכוון לפלח מסוים.
    """
    if not layers:
        return None
    # לכל סוג תוכן סדר עדיפויות אחר, כדי שיום אחד יכסה כמה פלחים
    offset = {"POV": 0, "ריל": 1, "קרוסלה": 2, "פוסט": 3, "סטורי": 4}.get(kind, 0)
    order = layers[offset % len(layers):] + layers[: offset % len(layers)]
    for l in order:
        if l not in used_today:
            return l
    return order[0]


def extract_layers(voice_text):
    """שולף את פלחי הקהל מקובץ הקול, אם יש שם פילוח.

    מחפש כותרת "למי אני מוכר" ולוקח ממנה שורות רשימה. זה לא מדע מדויק,
    ובכוונה סלחני: עדיף להחזיר רשימה ריקה מאשר לנחש פלחים שלא קיימים.
    """
    m = re.search(r"##\s*למי אני מוכר(.*?)(?=\n##|\Z)", voice_text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).split("\n"):
        s = line.strip(" -*•\t")
        if 12 < len(s) < 90 and not s.startswith("#"):
            out.append(s[:60])
    return out[:4]


def pick_format(kind, history):
    """הפורמט שהכי מזמן לא היה. לא 'הראשון הפנוי' — זה נותן סדר קבוע."""
    avail = FORMATS[kind]
    never = [f for f in avail if f not in history]
    if never:
        return never[0]
    return sorted(avail, key=lambda f: history.get(f, ""))[0]


# ── הריצה ───────────────────────────────────────────────────────────


def run(test_mode=False):
    setup_logging()
    log("=" * 60)
    log("ריצה התחילה" + (" (מצב בדיקה)" if test_mode else ""))

    for d in list(FOLDERS.values()) + [DAILY_SUMMARY, LEARNED]:
        safe(d.mkdir, parents=True, exist_ok=True)

    if not VOICE_FILE.exists():
        raise RuntimeError(f"קובץ הקול לא נמצא: {VOICE_FILE}")
    voice = VOICE_FILE.read_text(encoding="utf-8")

    state = load_state()
    new_files = find_new(state)
    if test_mode:
        new_files = new_files[:1]
    log(f"נמצאו {len(new_files)} קבצים חדשים")

    if not new_files:
        log("אין חומר חדש")
        safe(DAILY_SUMMARY.mkdir, parents=True, exist_ok=True)
        (DAILY_SUMMARY / f"{datetime.now():%Y-%m-%d}.md").write_text(
            f"# {datetime.now():%Y-%m-%d}\n\nלא היו פגישות חדשות", encoding="utf-8")
        return

    analyses = []
    for i, f in enumerate(new_files, 1):
        log(f"[{i}/{len(new_files)}] {f.name}")
        raw, known = read_transcript(f)
        if not raw or len(raw) < 200:
            log("  קצר מדי או לא נקרא, מדלג")
            continue

        clean = anonymize(raw, known)
        prompt = build_analysis_prompt(clean, voice)
        result = ask_claude(prompt, "analysis", min_len=800)
        if not result:
            log("  הניתוח נכשל — לא מסמן כמטופל, ינוסה שוב מחר")
            continue

        # הניתוח נשמר ומוזן למייל היומי, אז הוא חייב לעבור את אותה
        # בדיקה כמו הקופי. בלי זה שם שהוסק מהקשר מגיע ישר לתיבה.
        leaked = has_leaked_names(result)
        if leaked:
            log(f"  ⚠️ נמצא שם בניתוח ({leaked}) — מנקה")
            result = ask_claude(
                f"""הסר מהטקסט הבא כל שם של אדם, עסק או מקום, והחלף
ב-[הושמט]. אל תשנה שום דבר אחר. החזר את הטקסט המתוקן בלבד.

---
{result}""", "analysis_scrub", min_len=500) or result
            if has_leaked_names(result):
                log("  ❌ הניתוח עדיין מכיל שם — מדלג על הפגישה")
                continue

        stamp = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        out = LEARNED / f"{stamp}__{f.stem[:40]}__{abs(hash(f.name)) % 100000}.md"
        out.write_text(result, encoding="utf-8")
        analyses.append(result)
        if not test_mode:
            state["processed_files"].append(f.name)
            safe(f.unlink)  # המקור נמחק — ראה privacy.md
        log(f"  ✅ נשמר ({len(result):,} תווים)")

    if not analyses:
        raise RuntimeError("אף קובץ לא עובד בהצלחה")

    ALL_KINDS = ["POV", "ריל", "קרוסלה", "פוסט", "סטורי"]
    layers = extract_layers(voice)
    if layers:
        log(f"פלחי קהל מקובץ הקול: {len(layers)}")
    used_layers = []
    today = f"{datetime.now():%Y-%m-%d}"
    created = []

    # כל פגישה מקבלת את מלוא תשומת הלב שלה
    jobs = []
    for m_idx in range(len(analyses)):
        for k in range(1 if test_mode else PIECES_PER_MEETING):
            jobs.append((ALL_KINDS[(m_idx + k) % len(ALL_KINDS)], m_idx))
        if test_mode:
            break
    log(f"{len(analyses)} פגישות → {len(jobs)} פיסות תוכן")

    for kind, m_idx in jobs:
        code = pick_format(kind, state["format_history"])
        layer = pick_audience_layer(kind, used_layers, layers)
        log(f"כותב {kind} ({code}) מפגישה {m_idx + 1}" + (f" · {layer[:30]}" if layer else ""))
        prompt = build_content_prompt(
            kind, code, analyses[m_idx], voice, LEARNED, layer
        )
        content = ask_claude(prompt, f"content_{kind}", min_len=300)
        if not content:
            log(f"  {kind} נכשל, מדלג")
            continue

        leaked = has_leaked_names(content)
        if leaked:
            log(f"  ⚠️ נמצא שם בפלט ({leaked}) — כותב מחדש")
            content = ask_claude(
                prompt + "\n\n⚠️ אסור בהחלט להזכיר שמות של אנשים.",
                f"content_{kind}_retry", min_len=300)
            if not content or has_leaked_names(content):
                log(f"  ❌ {kind} עדיין מכיל שם — מדלג")
                continue

        folder = FOLDERS[kind]
        safe(folder.mkdir, parents=True, exist_ok=True)
        p = folder / f"{today}_{code}_{m_idx + 1}.md"
        p.write_text(content, encoding="utf-8")
        save_docx(content, p.with_suffix(".docx"), title=f"{kind} · {today}")
        upload_to_drive(p, kind, folder.name)
        created.append(p)
        if layer:
            used_layers.append(layer)
            if len(used_layers) >= len(layers):
                used_layers = []
        if not test_mode:
            state["format_history"][code] = today
        log(f"  ✅ נשמר ב{folder.name}/ ({p.stat().st_size:,} בתים)")

    # סיכום יומי — מה נוצר היום, במקום אחד
    if created:
        safe(DAILY_SUMMARY.mkdir, parents=True, exist_ok=True)
        lines = [f"# {today}", "", f"נותחו {len(analyses)} פגישות", "", "## נוצר היום", ""]
        lines += [f"- {p.parent.name}/{p.name}" for p in created]
        (DAILY_SUMMARY / f"{today}.md").write_text("\n".join(lines), encoding="utf-8")

    if not test_mode:
        state["last_run"] = datetime.now().isoformat()
        save_state(state)

    log("=" * 60)
    log(f"סיום. נוצרו {len(created)} תכנים ב{CONTENT_ROOT.name}/")


def build_analysis_prompt(transcript, voice):
    return f"""אתה מנתח פגישת לקוח עבור בעל עסק, כדי ללמוד על הקהל שלו.

קרא קודם: {SKILL_REFS}/privacy.md

⚠️ הכלל הקריטי: **דפוסים וציטוטים כן, שמות ופרטים מזהים לא.**
ציטוט מותר ואפילו רצוי — מה שאסור זה לייחס אותו לאדם מזוהה.

הקול והעסק של בעל העסק:
{voice[:3000]}

הדוברים מסומנים [דובר 1], [דובר 2] וכו'. **קודם כל זהה מההקשר מי מהם
בעל העסק ומי הלקוח** — בעל העסק הוא זה שמייעץ, שואל שאלות אבחון, ומציע
פתרונות. אל תניח שהדובר הראשון הוא בעל העסק; בשיחות רבות הלקוח פותח.

החזר בדיוק במבנה הזה:

## על מה דיברו
## הכאבים שעלו
## השאלות ששאלו
## ציטוטים (5-10, verbatim, בלי מקור)
## איך הם מנסחים את זה — מילים וביטויים
## 4 זוויות אפשריות לתוכן

---
התמלול:

{transcript[:40000]}
"""


def build_content_prompt(kind, code, analysis, voice, learned_dir, layer=None):
    format_ref = (
        f"{SKILL_REFS}/pov.md — הפורמט הזה הוא POV. קרא את הקובץ במלואו,\n"
        "   יש לו חוקי קול משלו ונקודת כשל שקל ליפול בה"
        if kind == "POV"
        else f"{SKILL_REFS}/formats.md — מצא את הפרומפט {code} והפעל אותו בדיוק"
    )
    layer_line = (
        f"\n⚠️ הפיסה הזו מכוונת לפלח קהל מסוים: **{layer}**\n"
        "כתוב אליו, לא לכולם. פיסה שמנסה לדבר לכל הקהל לא מדברת לאף אחד.\n"
        if layer else ""
    )
    return f"""אתה כותב {kind} עבור בעל עסק, בקול שלו.

חובה לקרוא לפני שאתה כותב:
{format_ref}
{SKILL_REFS}/privacy.md — הכללים על שמות

⚠️ סדר עדיפויות כשיש התנגשות: הקול > הסודיות > מבנה הפורמט.

⚠️ אסור להזכיר שמות של אנשים, עסקים או מקומות. ציטוטים מותרים בלי מקור.
⚠️ אסור להמציא ציטוטים. רק מה שבניתוח.

הקול של בעל העסק:
{voice}
{layer_line}

מה שנלמד על הקהל עד היום: {learned_dir}

---
הניתוח של הפגישה:

{analysis}

---

⚠️ לפני שאתה מחזיר — עבור על סעיף "מה אסור לי" בקובץ הקול, ובדוק את
הפלט שלך מולו שורה אחר שורה. **כולל ההאשטגים והכותרות.**

זה לא סעיף להתרשמות. אם כתוב שם שמילה מסוימת אסורה, היא אסורה גם
בהאשטג, גם בכותרת, וגם כשהיא "מתאימה בול". בבדיקה אמיתית של הסוכן
הזה, מילה אסורה עברה בדיוק ככה — בהאשטג בתחתית הפוסט, אחרי שכל
גוף הטקסט היה נקי.

החזר רק את הפלט הסופי, אחרי שתיקנת.
"""


if __name__ == "__main__":
    test = "--test" in sys.argv
    try:
        run(test_mode=test)
    except Exception as e:
        setup_logging()
        tb = traceback.format_exc()
        log(f"FATAL: {e}")
        log(tb)
        try:
            (LOGS / "last_failure.txt").write_text(
                f"{datetime.now():%Y-%m-%d %H:%M}\n{e}\n\n{tb}", encoding="utf-8")
        except Exception:
            pass
        sys.exit(1)
