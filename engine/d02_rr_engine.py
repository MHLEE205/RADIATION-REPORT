# -*- coding: utf-8 -*-
"""
✦ Powered by LEENAI Automation System
D-02 RR 写真読み取りエンジン v7.0.2  (RPA PC · C:\\LEENAI_D02)

する事 (1 日 1 回 · 夜 21:00 · 形님 決定 2026-11-21):
  1. SharePoint PHOTO_V2 の 最近更新された IV フォルダの _RR を見る (読むだけ · C-01 エンジンのファイルは変えない)
  2. 「完了」 でない IV だけ · 一番早く受けたセットから 1 つずつ読む。
     使えるセット (4/4/4 · 12 個の数値が 2 回の読みで同じ · 合格) が 1 つ出たら その IV は 「完了」 → 以後 読まない
     (IV ごとに報告書は 1 つ · 早く撮った写真ほど CY CUT 2日前 に間に合う)
       AI ① セットの写真を 撮影順に 全部まとめて見せる → 測定の組 · 距離 (背景10m / 1m / 表面) · 地点 · 数値 · 機器名 · 写真の中の日付 · 画面の枠
       AI ② 画面の枠だけ切り出して 数値をもう一度読む (①と別に読む = 2 回読み)
       AI なし: EXIF 撮影日 · 鮮明さ · 数値の範囲と単位 · 4/4/4 の数
  3. 結果を RR_READ/{IV}.json に書く (D-02 専用フォルダ) → D-02 TOOL が読む
決まり:
  - 分からない所は null (推測しない)。TOOL では null = 担当者が選ぶ / 入力する
  - 数値は「AI の読み取り」— TOOL で担当者が写真と見比べて確認するまで確定しない (OCR は 100% ではない)
  - 写真の日付は読むだけ。変えない
使い方:
  python d02_rr_engine.py --login                 最初の 1 回 (Graph デバイスコードログイン · 形님)
  python d02_rr_engine.py                         いつもの実行 (作業スケジューラ 毎日 21:00)
  python d02_rr_engine.py --iv NAS2611-08 --dry   1 IV だけ · 書かずに結果を表示 (試験用)
  python d02_rr_engine.py --iv NAS2611-08 --force 読んだセットも読み直す
"""
import argparse, base64, datetime as dt, hashlib, io, json, logging, os, re, sys, time
import urllib.parse

ENGINE_VER = "7.0.2"   # 7.0.1: AI の答えの長さを写真の枚数に合わせる (LTO 25 枚で切れた) · 7.0.2: 2 回目は原寸から切り出して拡大 · IV は全部確認 (完了は PC に記録) · 単価 $2/$10 (토르 Step 3-6 보고)
HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("bg", "m1", "sf")
NEED = 4
MAX_VAL = 0.3      # 写真 1 枚の測定値の上限 (μSv/h) — 形님 決定
MAX_RATIO = 1.5    # 判定 b/a の上限 — 形님 決定

# ───────────────────────── 設定 ─────────────────────────
def load_config(path=None):
    p = path or os.path.join(HERE, "config.json")
    with open(p, encoding="utf-8") as f:
        c = json.load(f)
    c.setdefault("model", "claude-sonnet-5-5")
    c.setdefault("since_days", 0)           # 0 = IV フォルダを全部見る (IV フォルダの更新時刻は 写真が増えても変わらない · 토르 확인)
    c.setdefault("max_photos_per_set", 40)  # これより多いセットは AI に出さない (担当者が選ぶ)
    c.setdefault("daily_cost_cap_usd", 5.0) # 1 日の AI 費用の上限 (超えたら その日は止める)
    c.setdefault("img_long_edge", 1024)     # AI に送る写真の長い辺 (px)
    c.setdefault("data_dir", os.path.join(HERE, "data"))
    for k in ("tenant_id", "client_id", "drive_id", "photo_root", "read_root"):
        if not c.get(k):
            raise SystemExit(f"config.json に {k} がありません")
    return c

# ───────────────────────── Graph ─────────────────────────
class Graph:
    BASE = "https://graph.microsoft.com/v1.0/"
    SCOPES = ["Files.ReadWrite.All", "Sites.ReadWrite.All"]

    def __init__(self, cfg):
        import msal, requests
        self.req = requests
        self.cfg = cfg
        self.cache_path = os.path.join(cfg["data_dir"], "token_cache.bin")
        self.cache = msal.SerializableTokenCache()
        if os.path.exists(self.cache_path):
            self.cache.deserialize(open(self.cache_path, encoding="utf-8").read())
        self.app = msal.PublicClientApplication(cfg["client_id"], authority=f"https://login.microsoftonline.com/{cfg['tenant_id']}", token_cache=self.cache)

    def _save(self):
        if self.cache.has_state_changed:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            open(self.cache_path, "w", encoding="utf-8").write(self.cache.serialize())

    def login(self):
        flow = self.app.initiate_device_flow(scopes=self.SCOPES)
        print(flow["message"])
        r = self.app.acquire_token_by_device_flow(flow)
        self._save()
        if "access_token" not in r:
            raise SystemExit("ログイン失敗: " + str(r.get("error_description")))
        print("ログイン OK")

    def token(self):
        acc = self.app.get_accounts()
        r = self.app.acquire_token_silent(self.SCOPES, account=acc[0]) if acc else None
        self._save()
        if not r or "access_token" not in r:
            raise RuntimeError("Graph トークンがありません — python d02_rr_engine.py --login (形님)")
        return r["access_token"]

    def _get(self, url, stream=False):
        for i in range(4):
            r = self.req.get(url, headers={"Authorization": "Bearer " + self.token()}, timeout=60, stream=stream)
            if r.status_code in (429, 503, 504):
                time.sleep(int(r.headers.get("Retry-After", 5 * (i + 1)))); continue
            return r
        return r

    def path_url(self, rel):
        enc = "/".join(urllib.parse.quote(s, safe="") for s in rel.split("/"))
        return f"{self.BASE}drives/{self.cfg['drive_id']}/root:/{enc}:"

    def children(self, rel=None, item_id=None):
        url = (self.path_url(rel) + "/children" if rel else f"{self.BASE}drives/{self.cfg['drive_id']}/items/{item_id}/children") + "?$top=200"
        out = []
        while url:
            r = self._get(url)
            if r.status_code == 404: return None
            r.raise_for_status()
            d = r.json(); out += d.get("value", []); url = d.get("@odata.nextLink")
        return out

    def get_json(self, rel):
        r = self._get(self.path_url(rel) + "/content")
        if r.status_code == 404: return None
        r.raise_for_status()
        return r.json()

    def content(self, item_id):
        r = self._get(f"{self.BASE}drives/{self.cfg['drive_id']}/items/{item_id}/content")
        r.raise_for_status()
        return r.content

    def put_json(self, rel, obj):
        body = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        r = self.req.put(self.path_url(rel) + "/content", data=body, timeout=60,
                         headers={"Authorization": "Bearer " + self.token(), "Content-Type": "application/json"})
        r.raise_for_status()

# ───────────────────────── 写真 (AI なし) ─────────────────────────
def norm_taken(v):
    """'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD' / '' """
    if not v: return ""
    m = re.search(r"(\d{4})[-:/](\d{2})[-:/](\d{2})[ T](\d{2}):(\d{2})", str(v))
    if m: return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}"
    m = re.search(r"(\d{4})[-:/](\d{2})[-:/](\d{2})", str(v))
    return f"{m[1]}-{m[2]}-{m[3]}" if m else ""

def exif_taken(raw):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        ex = im.getexif()
        v = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
        return norm_taken(v)
    except Exception:
        return ""

def prep_image(raw, long_edge, keep_full=False):
    """AI に送る JPEG (向きを直して 縮小) · 縮小した画像 (· 原寸の画像 = 2 回目の切り出し用)"""
    from PIL import Image, ImageOps
    full = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    im = full
    s = min(1.0, long_edge / max(im.size))
    if s < 1: im = im.resize((round(im.width * s), round(im.height * s)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=85)
    return (b.getvalue(), im, full) if keep_full else (b.getvalue(), im)

def sharpness(im, box=None):
    """ラプラシアン分散 → 0..1 (TOOL と同じ物差し)"""
    import numpy as np
    if box:
        w, h = im.size
        im = im.crop((w * box[0] / 1000, h * box[1] / 1000, w * box[2] / 1000, h * box[3] / 1000))
    g = im.convert("L"); s = min(1.0, 320 / max(g.size)); g = g.resize((max(8, round(g.width * s)), max(8, round(g.height * s))))
    a = np.asarray(g, dtype=np.float32)
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return round(float(min(1.0, lap.var() / 2000)), 3)

def crop_jpeg(im, box, margin=0.15, min_w=800):
    """画面の枠を 原寸の画像から切り出し · 小さければ 幅 min_w まで拡大 (7.0.2 — 縮小画像からだと小さすぎて読めなかった)"""
    from PIL import Image
    w, h = im.size
    mx, my = (box[2] - box[0]) * margin, (box[3] - box[1]) * margin
    x0, y0, x1, y1 = max(0, box[0] - mx), max(0, box[1] - my), min(1000, box[2] + mx), min(1000, box[3] + my)
    c = im.crop((w * x0 / 1000, h * y0 / 1000, w * x1 / 1000, h * y1 / 1000))
    if c.width < min_w:
        s = min_w / max(1, c.width)
        c = c.resize((min_w, max(1, round(c.height * s))), Image.LANCZOS)
    b = io.BytesIO(); c.save(b, "JPEG", quality=92)
    return b.getvalue()

def shot_key(p):
    num = [int(x) for x in re.findall(r"\d+", p["file"])] or [0]
    return (p.get("taken") or "9999", num, p["file"])

# ───────────────────────── AI ─────────────────────────
PROMPT_SET = """You are reading radiation-measurement photos sent by a Japanese waste-paper baling yard for ONE export shipment.
The photos are numbered P1..P{n} in shooting order (best known order). Each photo shows a hand-held radiation meter in front of paper bales.
Korean rules: for each measurement, 4 photos at "bg" (background, the FARTHEST from the bales), 4 at "m1" (about 1 m), 4 at "sf" (surface, the meter touching or almost touching the bales).

How to decide distance — compare the photos WITH EACH OTHER (do not judge each photo alone; "10 m" photos are often only 3-5 m away):
- the farthest group = bg (floor, whole bale stacks, building visible); the closest group = sf (bale texture/print fills the frame, wire bands large, or the meter is laid on the bale); the middle group = m1.
- the same distance is usually shot 4 times in a row; the order of the three groups differs between yards.
- if two different meters, or two different times far apart, appear in the set, they are different measurements: give each its own "session" (S1, S2 ...).
- "point" = 1..4 inside the same session and kind, in shooting order.
For each photo also read:
- "value": the MAIN dose-rate number exactly as displayed (e.g. "00.09", "0.130", "0.031"). For LifeBasis meters read "Dose Rate", NOT "Average Dose Rate" or "Total Dose". null if the screen is off, blurred, or you are not sure.
- "unit": the unit shown next to the value (e.g. "μSv/h", "CPM"), null if not visible.
- "screen_on": false if the meter screen is off/blank.
- "box": [x0,y0,x1,y1] of the main value digits, integers 0-1000 relative to the image width/height. null if not visible.
- "device": the meter brand/model printed on it (e.g. "LifeBasis", "RANGER", "IWATSU SV-2000"), null if not printed.
- "stamp": a date/time printed on the photo by the camera or phone (NOT the meter's own clock), as "YYYY-MM-DD HH:MM" or "YYYY-MM-DD", null if none. Read MM/DD/YYYY correctly.
If you are not sure of a kind, use null. Never guess.
Answer ONLY with JSON, no other text:
{{"photos":[{{"p":1,"session":"S1","kind":"bg|m1|sf|null","point":1,"value":"00.09","unit":"μSv/h","screen_on":true,"box":[0,0,0,0],"device":"...","stamp":"..."}}]}}"""

PROMPT_VALUE = """Each image is a close crop of a radiation meter screen, labelled C1..C{n}.
Read the MAIN dose-rate number exactly as displayed (e.g. "00.09", "0.130"). For LifeBasis meters read the "Dose Rate" line, not "Average Dose Rate" or "Total Dose".
Use null if the digits are not clearly readable. Never guess.
Answer ONLY with JSON: {{"values":[{{"c":1,"value":"00.09"}}]}}"""

PRICE = {"in": 2.0 / 1e6, "out": 10.0 / 1e6}   # USD / token (Sonnet 5.5 · 토르 확인 2026-11-21 · 費用上限の計算用)

class AI:
    def __init__(self, cfg, cost):
        import requests
        self.req, self.cfg, self.cost = requests, cfg, cost
        self.key = cfg.get("anthropic_key") or os.environ.get("ANTHROPIC_API_KEY") or self._keyring()
        if not self.key: raise SystemExit("Anthropic API キーがありません (keyring 'LEENAI_ANTHROPIC_API_KEY' か 環境変数 ANTHROPIC_API_KEY)")

    @staticmethod
    def _keyring():
        try:
            import keyring
            return keyring.get_password("LEENAI_ANTHROPIC_API_KEY", "LEENAI") or ""
        except Exception:
            return ""

    def ask(self, prompt, images, labels, max_tokens=4000):
        if self.cost.over():
            raise RuntimeError("今日の AI 費用の上限に達しました")
        content = []
        for lab, jpg in zip(labels, images):
            content.append({"type": "text", "text": lab})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpg).decode()}})
        content.append({"type": "text", "text": prompt})
        for i in range(3):
            r = self.req.post("https://api.anthropic.com/v1/messages", timeout=180,
                              headers={"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                              json={"model": self.cfg["model"], "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]})
            if r.status_code in (429, 500, 529):
                time.sleep(10 * (i + 1)); continue
            r.raise_for_status()
            d = r.json()
            if d.get("stop_reason") == "max_tokens":
                raise RuntimeError(f"AI の答えが途中で切れました (max_tokens {max_tokens}) — このセットは書きません")
            u = d.get("usage", {})
            self.cost.add(u.get("input_tokens", 0) * PRICE["in"] + u.get("output_tokens", 0) * PRICE["out"])
            txt = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
            return parse_json(txt)
        raise RuntimeError("AI が応答しません")

def parse_json(txt):
    t = re.sub(r"```(?:json)?", "", txt or "").strip()
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0: raise ValueError("AI の答えが JSON ではありません")
    return json.loads(t[s:e + 1])

class Cost:
    """1 日の AI 費用 (data/cost/YYYY-MM-DD.json)"""
    def __init__(self, cfg):
        self.cap = float(cfg["daily_cost_cap_usd"])
        self.path = os.path.join(cfg["data_dir"], "cost", dt.date.today().isoformat() + ".json")
        self.usd = json.load(open(self.path))["usd"] if os.path.exists(self.path) else 0.0
    def add(self, usd):
        self.usd += usd
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump({"usd": round(self.usd, 4)}, open(self.path, "w"))
    def over(self): return self.usd >= self.cap

# ───────────────────────── 確かめ (AI なし · 試験できる純粋な関数) ─────────────────────────
UNIT_OK = re.compile(r"^\s*[μµu]\s*sv\s*/\s*h\s*$", re.I)

def parse_value(v, unit):
    """'00.09' → 0.09 · 単位が μSv/h 以外 / 範囲外 / 読めない → None"""
    if v is None: return None
    if unit is not None and not UNIT_OK.match(str(unit)): return None
    s = str(v).strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,3}(\.\d{1,4})?", s): return None
    x = float(s)
    return x if 0 <= x < 10 else None

def valid_box(b):
    if not isinstance(b, list) or len(b) != 4: return None
    try: n = [int(round(float(x))) for x in b]
    except Exception: return None
    if any(x < 0 or x > 1000 for x in n) or n[2] <= n[0] or n[3] <= n[1]: return None
    return n

def check_stamp(stamp, set_name):
    """写真の中の日付: メールを受けた日 (セット名 YYYYMMDD) より後 · 60 日より前 → 使わない"""
    t = norm_taken(stamp)
    m = re.match(r"(\d{4})(\d{2})(\d{2})", set_name or "")
    if not t or not m: return t
    recv = dt.date(int(m[1]), int(m[2]), int(m[3]))
    try: d = dt.date.fromisoformat(t[:10])
    except ValueError: return ""
    return t if recv - dt.timedelta(days=60) <= d <= recv else ""

def finalize(photos, ai_rows, set_name):
    """AI ① の答えを 写真の行に合わせ · 確かめる。photos: [{file, taken(EXIF), sharp_fn}] (撮影順)"""
    by_p = {}
    for r in (ai_rows or []):
        try: by_p[int(r.get("p"))] = r
        except Exception: pass
    out = []
    for i, ph in enumerate(photos, 1):
        r = by_p.get(i, {})
        kind = r.get("kind") if r.get("kind") in KINDS else None
        screen = r.get("screen_on") is not False
        rec = {
            "file": ph["file"],
            "rr_session": str(r.get("session") or "S1")[:8],
            "rr_kind": kind,
            "rr_point": None,
            "rr_value": parse_value(r.get("value"), r.get("unit")) if screen else None,
            "rr_value2": None,
            "rr_box": valid_box(r.get("box")),
            "rr_screen_ok": screen,
            "rr_device": (str(r["device"]).strip()[:40] if r.get("device") else None),
            "rr_taken": ph.get("taken") or check_stamp(r.get("stamp"), set_name) or None,
            "rr_taken_src": "exif" if ph.get("taken") else ("stamp" if check_stamp(r.get("stamp"), set_name) else None),
            "rr_sharp": None,
            "how": "ai_set" if kind else None,
            "_ai_point": r.get("point"),
        }
        out.append(rec)
    # 地点: 同じ測定 · 同じ距離 の中で AI の point が 1..n で重ならなければ使う · それ以外は撮影順
    groups = {}
    for idx, rec in enumerate(out):
        if rec["rr_kind"]: groups.setdefault((rec["rr_session"], rec["rr_kind"]), []).append((idx, rec))
    for (_, _), lst in groups.items():
        pts = [rec["_ai_point"] for _, rec in lst]
        ok = all(isinstance(p, int) and 1 <= p <= len(lst) for p in pts) and len(set(pts)) == len(pts)
        if ok:
            for _, rec in lst: rec["rr_point"] = rec["_ai_point"]
        else:
            for n, (_, rec) in enumerate(lst, 1): rec["rr_point"] = n
    for rec in out: rec.pop("_ai_point", None)
    return out

def session_summary(recs):
    """測定ごとの 4/4/4 の数 · 機器名"""
    s = {}
    for r in recs:
        x = s.setdefault(r["rr_session"], {"bg": 0, "m1": 0, "sf": 0, "devices": set(), "photos": 0})
        x["photos"] += 1
        if r["rr_kind"] and r["rr_screen_ok"]: x[r["rr_kind"]] += 1
        if r["rr_device"]: x["devices"].add(r["rr_device"])
    return {k: {"bg": v["bg"], "m1": v["m1"], "sf": v["sf"], "photos": v["photos"], "devices": sorted(v["devices"]),
                "complete": all(v[k2] >= NEED for k2 in KINDS)} for k, v in s.items()}

def received_date(set_name):
    """セット名 YYYYMMDD_hhmm_… = メールを受けた日"""
    m = re.match(r"(\d{4})(\d{2})(\d{2})_", set_name or "")
    return f"{m[1]}-{m[2]}-{m[3]}" if m else ""

def plan_session(recs, session):
    """TOOL と同じ選び方: 区分ごとに 画面が点いている写真から 鮮明な 4 枚 → 使えるか (4/4/4 · 2 回の読みが同じ · 合格)"""
    pick = {}
    for k in KINDS:
        c = [r for r in recs if r["rr_session"] == session and r["rr_kind"] == k and r["rr_screen_ok"]]
        pick[k] = sorted(c, key=lambda r: -(r.get("rr_sharp") or 0))[:NEED]
    complete = all(len(pick[k]) >= NEED for k in KINDS)
    if not complete:
        return {"complete": False, "agree": False, "pass": None}
    chosen = [r for k in KINDS for r in pick[k]]
    agree = all(r["rr_value"] is not None and r["rr_value2"] is not None and abs(r["rr_value"] - r["rr_value2"]) < 1e-9 for r in chosen)
    vals = {k: [r["rr_value"] for r in pick[k]] for k in KINDS}
    pss = None
    if all(v is not None for k in KINDS for v in vals[k]):
        a = sum(vals["bg"]) / NEED; b = sum(vals["sf"]) / NEED
        pss = bool(a > 0 and b / a <= MAX_RATIO and all(v <= MAX_VAL for k in KINDS for v in vals[k]))
    return {"complete": True, "agree": agree, "pass": pss}

def set_usable(set_out):
    """このセットで報告書が作れるか (どれか 1 つの測定が 4/4/4 · 2 回の読みが同じ · 合格)"""
    for ses in set_out["sessions"]:
        p = plan_session(set_out["photos"], ses)
        if p["complete"] and p["agree"] and p["pass"]:
            return ses
    return None

# ───────────────────────── 1 セット ─────────────────────────
def read_set(g, ai, cfg, set_name, items, log):
    photos = []
    for it in items:
        raw = g.content(it["id"])
        jpg, im, full = prep_image(raw, cfg["img_long_edge"], keep_full=True)
        photos.append({"file": it["name"], "id": it["id"], "etag": it.get("eTag", ""), "taken": exif_taken(raw), "jpg": jpg, "im": im, "full": full})
    photos.sort(key=shot_key)
    if len(photos) > cfg["max_photos_per_set"]:
        log.warning(f"  {set_name}: {len(photos)} 枚 > {cfg['max_photos_per_set']} → AI に出さない (担当者が選ぶ)")
        recs = finalize(photos, [], set_name)
    else:
        ans = ai.ask(PROMPT_SET.format(n=len(photos)), [p["jpg"] for p in photos], [f"P{i}" for i in range(1, len(photos) + 1)],
                     max_tokens=tokens_for(len(photos), 350, 1500))
        recs = finalize(photos, ans.get("photos"), set_name)
        # AI ② 画面の枠だけで もう一度読む
        targets = [(i, r) for i, r in enumerate(recs) if r["rr_box"] and r["rr_screen_ok"]]
        if targets:
            crops = [crop_jpeg(photos[i]["full"], r["rr_box"]) for i, r in targets]
            ans2 = ai.ask(PROMPT_VALUE.format(n=len(crops)), crops, [f"C{n}" for n in range(1, len(crops) + 1)],
                          max_tokens=tokens_for(len(crops), 60, 800))
            vals = {}
            for v in ans2.get("values", []):
                try: vals[int(v.get("c"))] = v.get("value")
                except Exception: pass
            for n, (i, r) in enumerate(targets, 1):
                r["rr_value2"] = parse_value(vals.get(n), None)
    for p, r in zip(photos, recs):
        r["rr_sharp"] = sharpness(p["im"], r["rr_box"])
    fp = fingerprint(items)
    summ = session_summary(recs)
    for k, v in summ.items():
        log.info(f"  {set_name} {k}: bg {v['bg']} · 1m {v['m1']} · 表面 {v['sf']} / {v['photos']}枚 · 機器 {','.join(v['devices']) or '-'}")
    undated = sum(1 for r in recs if not r["rr_taken"])
    if undated:
        log.info(f"  {set_name}: 撮影日が分からない写真 {undated}枚 (メール受信日 {received_date(set_name) or '?'} で判断)")
    return {"set": set_name, "received": received_date(set_name), "fingerprint": fp, "read_at": dt.datetime.now().isoformat(timespec="seconds"),
            "engine_ver": ENGINE_VER, "model": cfg["model"], "sessions": summ, "undated": undated, "photos": recs}

def tokens_for(n, per_photo, base):
    """AI の答えの長さの上限 = 写真の枚数 × 1 枚分 + 余裕 (16000 まで)"""
    return int(min(16000, base + per_photo * n))

def fingerprint(items):
    h = hashlib.sha1()
    for it in sorted(items, key=lambda x: x["name"]):
        h.update((it["name"] + "|" + str(it.get("size", "")) + "|" + it.get("eTag", "")).encode())
    return h.hexdigest()[:16]

IMG_RE = re.compile(r"\.(jpe?g|png)$", re.I)

def read_iv(g, ai, cfg, iv, force, dry, log):
    base = f"{cfg['photo_root']}/{iv}/_RR"
    kids = g.children(base)
    if kids is None: return False
    out_rel = f"{cfg['read_root']}/{iv}.json"
    cur = (None if force else g.get_json(out_rel)) or {"iv_no": iv, "sets": []}
    if cur.get("status") == "done":
        return False                                   # この IV は 完了 (使えるセットがある) → 読まない
    done = {s["set"]: s for s in cur.get("sets", [])}
    changed = False
    # 一番早く受けたセットから (セット名 = 受信日時)
    for f in sorted([k for k in kids if "folder" in k], key=lambda x: x["name"]):
        items = [x for x in (g.children(item_id=f["id"]) or []) if "file" in x and IMG_RE.search(x["name"])]
        if not items: continue
        fp = fingerprint(items)
        if not (f["name"] in done and done[f["name"]].get("fingerprint") == fp):
            log.info(f"{iv} / {f['name']} ({len(items)}枚) 読み取り")
            try:
                done[f["name"]] = read_set(g, ai, cfg, f["name"], items, log)
                changed = True
            except Exception as e:
                log.error(f"{iv} / {f['name']} 失敗: {e}")
                if "上限" in str(e): raise
                continue
        ses = set_usable(done[f["name"]]) if f["name"] in done else None
        if ses:
            cur["status"], cur["done_set"], cur["done_session"] = "done", f["name"], ses
            changed = True
            log.info(f"{iv} 完了 — {f['name']} {ses} で報告書が作れます (残りのセットは読みません)")
            break
    if changed:
        cur["sets"] = [done[k] for k in sorted(done)]
        cur["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        cur["engine"] = f"D-02 RR engine v{ENGINE_VER}"
        cur["note"] = "AI の読み取り (未確認)。D-02 TOOL で担当者が写真と見比べて確定する。✦ Powered by LEENAI Automation System"
        if dry:
            print(json.dumps(cur, ensure_ascii=False, indent=1))
        else:
            g.put_json(out_rel, cur)
            log.info(f"{iv} → {out_rel}")
    return changed

def done_cache_path(cfg): return os.path.join(cfg["data_dir"], "done_ivs.json")

def load_done(cfg):
    """「完了」 になった IV (PC に記録 · 毎回 SharePoint を読まずに飛ばす)"""
    try: return set(json.load(open(done_cache_path(cfg), encoding="utf-8")))
    except Exception: return set()

def save_done(cfg, done):
    os.makedirs(cfg["data_dir"], exist_ok=True)
    json.dump(sorted(done), open(done_cache_path(cfg), "w", encoding="utf-8"), ensure_ascii=False)

def recent_ivs(g, cfg):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg["since_days"])
    out = []
    for k in g.children(cfg["photo_root"]) or []:
        if "folder" not in k or k["name"].startswith("_"): continue
        if not cfg["since_days"]:
            out.append(k["name"]); continue
        t = k.get("lastModifiedDateTime", "")
        try: ok = dt.datetime.fromisoformat(t.replace("Z", "+00:00")) >= since
        except Exception: ok = True
        if ok: out.append(k["name"])
    return sorted(out)

def setup_log(cfg):
    d = os.path.join(cfg["data_dir"], "logs"); os.makedirs(d, exist_ok=True)
    log = logging.getLogger("d02"); log.setLevel(logging.INFO)
    if not log.handlers:
        fh = logging.FileHandler(os.path.join(d, dt.date.today().isoformat() + ".log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s")); log.addHandler(fh)
        sh = logging.StreamHandler(); sh.setFormatter(logging.Formatter("%(message)s")); log.addHandler(sh)
    return log

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true"); ap.add_argument("--iv"); ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true"); ap.add_argument("--config")
    a = ap.parse_args()
    cfg = load_config(a.config)
    os.makedirs(cfg["data_dir"], exist_ok=True)
    g = Graph(cfg)
    if a.login: g.login(); return
    log = setup_log(cfg)
    lock = os.path.join(cfg["data_dir"], "run.lock")
    if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 1800:
        log.info("前の実行が動いています — 今回は休み"); return
    open(lock, "w").write(str(os.getpid()))
    try:
        ai = AI(cfg, Cost(cfg))
        done_ivs = set() if a.force else load_done(cfg)
        ivs = [a.iv.strip().upper()] if a.iv else [x for x in recent_ivs(g, cfg) if x not in done_ivs]
        n = 0
        for iv in ivs:
            try:
                if read_iv(g, ai, cfg, iv, a.force, a.dry, log): n += 1
                if not a.dry:
                    cur = g.get_json(f"{cfg['read_root']}/{iv}.json")
                    if cur and cur.get("status") == "done":
                        done_ivs.add(iv); save_done(cfg, done_ivs)
            except RuntimeError as e:
                log.error(str(e)); break
        log.info(f"終了 · 読み取った IV {n} · 今日の AI 費用 ${ai.cost.usd:.2f}")
    finally:
        try: os.remove(lock)
        except OSError: pass

if __name__ == "__main__":
    main()
