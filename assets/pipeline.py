"""
הצד של הסוכן — מדבר עם ה-Pipeline בגוגל שיטס.

אין כאן מפתחות, אין Google Cloud, ואין ספריות חיצוניות.
רק כתובת אחת שהלקוח הדביק בהתקנה.
"""

import json
import urllib.request
import urllib.error

TIMEOUT = 60


class PipelineError(Exception):
    pass


class Pipeline:
    def __init__(self, web_app_url):
        if not web_app_url or not str(web_app_url).startswith("https://script.google.com/"):
            raise PipelineError(
                "כתובת ה-Pipeline חסרה או שגויה. היא מתקבלת בהתקנה, "
                "כשפורסים את הסקריפט בגיליון."
            )
        self.url = web_app_url

    # ---------- פעולות ----------

    def ping(self):
        """בדיקה שהגשר חי. מחזיר מספר הלשוניות בגיליון."""
        return self._call({"action": "ping"})

    def add(self, items, month=None):
        """
        items: רשימת dict עם המפתחות תאריך / סוג / הוק / לינק
        month: 0=ינואר … 11=דצמבר. ברירת מחדל: החודש הנוכחי
        """
        rows = [[
            it["תאריך"], it["סוג"], it["הוק"], it.get("לינק", ""), "", False
        ] for it in items]
        payload = {"action": "add", "rows": rows}
        if month is not None:
            payload["month"] = month
        return self._call(payload)

    def read(self, month=None):
        payload = {"action": "read"}
        if month is not None:
            payload["month"] = month
        return self._call(payload)["rows"]

    def approved(self, month=None):
        """רק מה שהלקוח סימן"""
        return [r for r in self.read(month) if r.get("approved")]

    # ---------- הקריאה עצמה ----------

    def _call(self, payload):
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise PipelineError(f"הגיליון החזיר שגיאה {e.code}. לבדוק שהפריסה פעילה.")
        except urllib.error.URLError as e:
            raise PipelineError(f"אין חיבור לגיליון: {e.reason}")

        if not body.get("ok"):
            raise PipelineError(body.get("error", "שגיאה לא ידועה מהגיליון"))
        return body["data"]
