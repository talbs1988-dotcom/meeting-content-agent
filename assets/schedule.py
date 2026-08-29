#!/usr/bin/env python3
"""מתקין את התזמון של הסוכן — מק, לינוקס וחלונות.

**למה קובץ ולא הוראות בפרוזה:** תיאור טקסטואלי של plist נכתב מחדש בכל
התקנה, ומספיק תו אחד שגוי כדי ש-launchd יסרב בשקט. כאן הכל נבנה
מתבנית, מאומת, ומדווח מה באמת עלה.

שלוש עבודות:
  לילי    21:00       קורא, מנתח, כותב
  בוקר    07:00       דופק — בודק שהלילי באמת רץ
  שבועי   יום קבוע    המסמך לאישור

**למה דופק נפרד:** סוכן שקרס לא יכול לשלוח הודעה שהוא קרס.

הרצה:
    python3 schedule.py <תיקיית-המנוע>            התקנה
    python3 schedule.py <תיקיית-המנוע> --status   מה רץ
    python3 schedule.py <תיקיית-המנוע> --remove   הסרה
"""

import json
import platform
import subprocess
import sys
from pathlib import Path

JOBS = [
    ("agent",     "agent.py",     "run_hour",       21, None),
    ("heartbeat", "heartbeat.py", "heartbeat_hour",  7, None),
    ("weekly",    "weekly.py",    "weekly_hour",     8, "weekly_day"),
]

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
  </array>
  <key>WorkingDirectory</key><string>{root}</string>
  <key>StartCalendarInterval</key>
  <dict>
{when}  </dict>
  <key>StandardOutPath</key><string>{root}/logs/{name}.out.log</string>
  <key>StandardErrorPath</key><string>{root}/logs/{name}.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>{path}</string>
  </dict>
</dict>
</plist>
"""


def _cfg(root):
    try:
        return json.loads((Path(root) / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _prefix(root):
    """תווית ייחודית, שלא תתנגש בסוכן אחר על אותו מחשב."""
    return f"com.{Path(root).name.replace(' ', '-').lower()[:24]}"


def _python():
    return sys.executable or "python3"


# ── מק ──────────────────────────────────────────────────────────────

def _mac(root, cfg, log):
    la = Path.home() / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    (Path(root) / "logs").mkdir(exist_ok=True)
    # ⚠️ ל-launchd אין את ה-PATH של הטרמינל. בלי זה `claude` לא נמצא,
    # והריצה נכשלת בכל לילה בלי שאף אחד יודע.
    path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    ok = []
    for name, script, hour_key, hour_def, day_key in JOBS:
        hour = int(cfg.get(hour_key, hour_def))
        when = f"    <key>Hour</key><integer>{hour}</integer>\n"
        when += "    <key>Minute</key><integer>0</integer>\n"
        if day_key:
            when += f"    <key>Weekday</key><integer>{int(cfg.get(day_key, 0))}</integer>\n"
        label = f"{_prefix(root)}.{name}"
        f = la / f"{label}.plist"
        f.write_text(PLIST.format(label=label, python=_python(),
                                  script=str(Path(root) / script), root=root,
                                  when=when, name=name, path=path), encoding="utf-8")

        r = subprocess.run(["plutil", "-lint", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"  ❌ {name}: ה-plist לא תקין — {r.stdout.strip()[:120]}")
            continue
        subprocess.run(["launchctl", "unload", str(f)],
                       capture_output=True, text=True)
        r = subprocess.run(["launchctl", "load", str(f)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            log(f"  ❌ {name}: launchctl סירב — {r.stderr.strip()[:120]}")
            continue
        ok.append((label, name, hour))
    return ok


# ── חלונות ──────────────────────────────────────────────────────────

def _windows(root, cfg, log):
    ok = []
    for name, script, hour_key, hour_def, day_key in JOBS:
        hour = int(cfg.get(hour_key, hour_def))
        label = f"{_prefix(root)}.{name}"
        cmd = ["schtasks", "/Create", "/F", "/TN", label,
               "/TR", f'"{_python()}" "{Path(root) / script}"',
               "/ST", f"{hour:02d}:00"]
        if day_key:
            days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
            cmd += ["/SC", "WEEKLY", "/D", days[int(cfg.get(day_key, 0)) % 7]]
        else:
            cmd += ["/SC", "DAILY"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"  ❌ {name}: {(r.stderr or r.stdout).strip()[:140]}")
            continue
        ok.append((label, name, hour))
    return ok


# ── לינוקס ──────────────────────────────────────────────────────────

def _linux(root, cfg, log):
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    keep = [l for l in cur.splitlines() if _prefix(root) not in l]
    ok = []
    for name, script, hour_key, hour_def, day_key in JOBS:
        hour = int(cfg.get(hour_key, hour_def))
        dow = str(int(cfg.get(day_key, 0))) if day_key else "*"
        keep.append(f"0 {hour} * * {dow} cd {root} && {_python()} {script}"
                    f"  # {_prefix(root)}.{name}")
        ok.append((f"{_prefix(root)}.{name}", name, hour))
    p = subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n",
                       capture_output=True, text=True)
    if p.returncode != 0:
        log(f"  ❌ crontab סירב: {p.stderr.strip()[:140]}")
        return []
    return ok


# ── אימות ───────────────────────────────────────────────────────────

def verify(root, log=print):
    """בודק שהעבודות באמת רשומות במערכת. לא סומך על 'ההתקנה הצליחה'."""
    pre = _prefix(root)
    sysname = platform.system()
    if sysname == "Darwin":
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    elif sysname == "Windows":
        out = subprocess.run(["schtasks", "/Query", "/FO", "LIST"],
                             capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    found = [n for _, n, _ in
             [(f"{pre}.{j[0]}", j[0], 0) for j in JOBS] if f"{pre}.{n}" in out]
    for _, name, _ in [(f"{pre}.{j[0]}", j[0], 0) for j in JOBS]:
        log(f"  {'✅' if name in found else '❌'} {name}")
    return found


def install(root, log=print):
    """מחזיר רשימת עבודות שבאמת עלו. לא זורק."""
    root = str(Path(root).resolve())
    cfg = _cfg(root)
    sysname = platform.system()
    fn = {"Darwin": _mac, "Windows": _windows}.get(sysname, _linux)
    log(f"מתקין תזמון ({sysname})")
    ok = fn(root, cfg, log)
    log("אימות מול המערכת:")
    real = verify(root, log)
    if len(real) < len(JOBS):
        log("⚠️ לא כל העבודות עלו. הסוכן לא ירוץ לבד עד שזה יתוקן")
    return real


def remove(root, log=print):
    pre = _prefix(root)
    sysname = platform.system()
    for name, *_ in JOBS:
        label = f"{pre}.{name}"
        if sysname == "Darwin":
            f = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
            subprocess.run(["launchctl", "unload", str(f)], capture_output=True)
            f.unlink(missing_ok=True)
        elif sysname == "Windows":
            subprocess.run(["schtasks", "/Delete", "/F", "/TN", label],
                           capture_output=True)
    if sysname not in ("Darwin", "Windows"):
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        keep = [l for l in cur.splitlines() if pre not in l]
        subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n",
                       capture_output=True, text=True)
    log("התזמון הוסר")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    root = sys.argv[1]
    if "--remove" in sys.argv:
        remove(root)
    elif "--status" in sys.argv:
        verify(root)
    else:
        install(root)
