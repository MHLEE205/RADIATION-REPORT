# -*- coding: utf-8 -*-
# ✦ Powered by LEENAI Automation System — D-02 エンジン v7.0 試験 (偽 SharePoint · 偽 AI · API キー不要)
import io, json, os, sys, tempfile, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d02_rr_engine as E
from PIL import Image, ImageFilter

P = F = 0
def ok(c, m):
    global P, F
    if c: P += 1; print("  ✔", m)
    else: F += 1; print("  ✘", m)

def jpg(w=640, h=480, blur=False, exif_dt=None, seed=1):
    import random
    random.seed(seed)
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = random.randint(0, 255)
            for dy in range(4):
                for dx in range(4):
                    if x + dx < w and y + dy < h: px[x + dx, y + dy] = (c, c, c)
    if blur: im = im.filter(ImageFilter.GaussianBlur(6))
    b = io.BytesIO()
    if exif_dt:
        ex = Image.Exif(); ifd = ex.get_ifd(0x8769); ifd[0x9003] = exif_dt
        im.save(b, "JPEG", exif=ex)
    else:
        im.save(b, "JPEG")
    return b.getvalue()

print("■ 確かめ (AI なし)")
ok(E.parse_value("00.09", "μSv/h") == 0.09, "'00.09' μSv/h → 0.09")
ok(E.parse_value("0.130", "uSv/h") == 0.13, "'0.130' uSv/h → 0.13")
ok(E.parse_value("0.13", "CPM") is None, "単位 CPM → 使わない")
ok(E.parse_value("0.1?", "μSv/h") is None, "読めない文字 → None")
ok(E.parse_value("12.5", None) is None, "10 以上 → None")
ok(E.parse_value(None, "μSv/h") is None, "null → None")
ok(E.valid_box([300, 200, 700, 500]) == [300, 200, 700, 500], "枠 OK")
ok(E.valid_box([700, 200, 300, 500]) is None and E.valid_box([0, 0, 1200, 5]) is None, "おかしな枠 → None")
ok(E.check_stamp("2026-11-19", "20261119_0859_e554") == "2026-11-19", "写真の日付 = 受信日 → 使う")
ok(E.check_stamp("2026-11-25 10:00", "20261119_0859_e554") == "", "受信日より後の日付 → 使わない (読み違い)")
ok(E.check_stamp("2025-01-01", "20261119_0859_e554") == "", "60 日より前 → 使わない")
ok(E.norm_taken("2026:11:19 08:46:30") == "2026-11-19 08:46", "EXIF 形式 → 揃える")
ok(E.exif_taken(jpg(exif_dt="2026:11:19 08:46:30")) == "2026-11-19 08:46", "JPEG の EXIF 撮影日時")
ok(E.exif_taken(jpg()) == "", "EXIF 無し → ''")
_, sharp_im = E.prep_image(jpg(), 1024); _, blur_im = E.prep_image(jpg(blur=True), 1024)
ok(E.sharpness(sharp_im) > E.sharpness(blur_im) * 3, f"鮮明さ: 鮮明 {E.sharpness(sharp_im)} > ぼけ {E.sharpness(blur_im)}")
ok(E.prep_image(jpg(4000, 3000), 1024)[1].size == (1024, 768), "AI に送る写真 = 長い辺 1024")
ok(E.parse_json('```json\n{"a":1}\n```') == {"a": 1}, "AI の答えの ``` を外して読む")

print("■ finalize (地点 · 測定 · 値)")
photos = [{"file": f"IMG_{i}.JPG", "taken": ""} for i in range(1, 13)]
rows = [{"p": i, "session": "S1", "kind": k, "point": None, "value": "00.09", "unit": "μSv/h", "screen_on": True,
         "box": [300, 300, 700, 600], "device": "LifeBasis", "stamp": "2026-11-19"}
        for i, k in zip(range(1, 13), ["m1"] * 4 + ["bg"] * 4 + ["sf"] * 4)]
rows[2]["kind"] = "far"          # 変な区分 → null
rows[5]["screen_on"] = False      # 画面が消えている → 値 null
rec = E.finalize(photos, rows, "20261119_0859_x")
ok(rec[2]["rr_kind"] is None, "知らない区分 → null (担当者が選ぶ)")
ok(rec[5]["rr_value"] is None and rec[5]["rr_screen_ok"] is False, "画面が消えている → 値 null")
ok([r["rr_point"] for r in rec if r["rr_kind"] == "bg"] == [1, 2, 3, 4], "AI の地点が無い → 撮影順に 1..4")
ok(rec[0]["rr_taken"] == "2026-11-19" and rec[0]["rr_taken_src"] == "stamp", "EXIF 無し → 写真の中の日付")
rows2 = [dict(r, point=p) for r, p in zip(rows, [4, 3, 2, 1] * 3)]
rec2 = E.finalize(photos, rows2, "20261119_0859_x")
ok([r["rr_point"] for r in rec2 if r["rr_kind"] == "sf"] == [4, 3, 2, 1], "AI の地点が正しい → そのまま")
rows3 = [dict(r, point=1) for r in rows]
rec3 = E.finalize(photos, rows3, "20261119_0859_x")
ok([r["rr_point"] for r in rec3 if r["rr_kind"] == "sf"] == [1, 2, 3, 4], "AI の地点が重なる → 撮影順")
s = E.session_summary(rec)
ok(s["S1"]["complete"] is False and s["S1"]["m1"] == 3, "4/4/4 が揃わない → complete False")

print("■ 全体 (偽 SharePoint · 偽 AI · --dry)")
class FakeGraph:
    def __init__(self):
        self.files = {f"IMG_{8971 + i}.JPG": jpg(seed=i, exif_dt=f"2026:11:19 08:{45 + i // 10}:{i:02d}") for i in range(1, 15)}
        self.written = {}
    def children(self, rel=None, item_id=None):
        if rel and rel.endswith("/NAS2611-08/_RR"):
            return [{"name": "20261119_0859_e554003a", "id": "FOLD", "folder": {}}, {"name": "_kinds.json", "id": "K", "file": {}}]
        if item_id == "FOLD":
            return [{"name": n, "id": "I|" + n, "file": {}, "size": len(b), "eTag": "e1"} for n, b in self.files.items()]
        return None
    def get_json(self, rel): return self.written.get(rel)
    def content(self, item_id): return self.files[item_id.split("|")[1]]
    def put_json(self, rel, obj): self.written[rel] = obj

class FakeAI:
    def __init__(self): self.calls = []; self.cost = type("C", (), {"usd": 0.0})()
    def ask(self, prompt, images, labels, max_tokens=4000):
        self.calls.append(len(images))
        if prompt.startswith("You are reading"):
            kinds = (["m1"] * 4 + ["bg"] * 4 + ["sf"] * 4 + ["m1", None] + [None] * 10)[:len(images)]
            vals = (["00.13", "00.04", "00.09", "00.06", "00.09", "00.11", "00.09", "00.09", "00.09", "00.06", "00.06", "00.06", "00.10", None] + [None] * 10)[:len(images)]
            return {"photos": [{"p": i + 1, "session": "S1", "kind": kinds[i], "point": None, "value": vals[i], "unit": "μSv/h",
                                "screen_on": vals[i] is not None, "box": [300, 300, 700, 600], "device": "LifeBasis", "stamp": "2026-11-19"}
                               for i in range(len(images))]}
        return {"values": [{"c": i + 1, "value": ("00.19" if i == 1 else "00.09")} for i in range(len(images))]}

cfg = {"photo_root": "PV2", "read_root": "RR_READ", "img_long_edge": 1024, "max_photos_per_set": 40, "model": "test"}
log = logging.getLogger("t"); log.addHandler(logging.NullHandler())
g, ai = FakeGraph(), FakeAI()
ch = E.read_iv(g, ai, cfg, "NAS2611-08", False, False, log)
out = g.written.get("RR_READ/NAS2611-08.json")
ok(ch and out is not None, "RR_READ/NAS2611-08.json に書いた")
ok(ai.calls[:2] == [14, 13] and len(ai.calls) == 3, f"AI 呼び出し (セット 14 · 画面の枠 13 · 7.0.3 から 合わない写真だけ 3 回目) → {ai.calls}")
ph = out["sets"][0]["photos"]
ok([p["file"] for p in ph][:3] == ["IMG_8972.JPG", "IMG_8973.JPG", "IMG_8974.JPG"], "撮影順 (EXIF) に並ぶ")
ok(all(p["rr_taken"].startswith("2026-11-19") and p["rr_taken_src"] == "exif" for p in ph), "撮影日時 = EXIF")
ok(ph[0]["rr_value"] == 0.13 and ph[1]["rr_value"] == 0.04 and ph[1]["rr_value2"] == 0.19, "1 回目と 2 回目の値を両方残す (違えば TOOL で赤)")
ok(ph[13]["rr_value"] is None and ph[13]["rr_screen_ok"] is False and ph[13]["rr_kind"] is None, "画面が消えた写真 → 値・区分 null")
ok(out["sets"][0]["sessions"]["S1"]["complete"] is True and out["sets"][0]["sessions"]["S1"]["m1"] == 5, "4/4/4 揃う (1m は予備含め 5)")
ok(all(isinstance(p["rr_sharp"], float) for p in ph), "鮮明さを全写真に")
ok("Powered by LEENAI Automation System" in out["note"], "Powered by 表記")
ai2 = FakeAI()
ch2 = E.read_iv(g, ai2, cfg, "NAS2611-08", False, False, log)
ok(ch2 is False and ai2.calls == [], "同じセットは 2 回目は読まない (AI 費用 0)")
g.files["IMG_8999.JPG"] = jpg(seed=99)
ch3 = E.read_iv(g, ai2, cfg, "NAS2611-08", False, False, log)
ok(ch3 and ai2.calls[0] == 15, "写真が増えたセットは 読み直す")
ok(E.read_iv(g, ai2, cfg, "NONE", False, False, log) is False, "_RR が無い IV → 何もしない")


print("■ IV ごとに 1 セット (早いセットから · 使えたら 完了)")
class Graph2(FakeGraph):
    def __init__(self):
        super().__init__()
        self.sets = {"20261120_1510_late": {f"L_{i:02d}.JPG": jpg(seed=100 + i) for i in range(12)},
                     "20261119_0859_early": {f"E_{i:02d}.JPG": jpg(seed=200 + i) for i in range(12)}}
        self.reads = []
    def children(self, rel=None, item_id=None):
        if rel and rel.endswith("/IV2/_RR"):
            return [{"name": n, "id": "S|" + n, "folder": {"childCount": 12}} for n in self.sets]
        if item_id and item_id.startswith("S|"):
            n = item_id[2:]; self.reads.append(n)
            return [{"name": f, "id": "J|" + n + "|" + f, "file": {}, "size": 1, "eTag": "e"} for f in self.sets[n]]
        return None
    def content(self, item_id):
        _, n, f = item_id.split("|"); return self.sets[n][f]
class GoodAI(FakeAI):
    def ask(self, prompt, images, labels, max_tokens=4000):
        self.calls.append(len(images))
        if prompt.startswith("You are reading"):
            ks = ["bg"] * 4 + ["m1"] * 4 + ["sf"] * 4
            return {"photos": [{"p": i + 1, "session": "S1", "kind": ks[i], "point": None, "value": "0.10", "unit": "μSv/h", "screen_on": True,
                                "box": [300, 300, 700, 600], "device": "RANGER", "stamp": None} for i in range(len(images))]}
        return {"values": [{"c": i + 1, "value": "0.10"} for i in range(len(images))]}
g2, ai3 = Graph2(), GoodAI()
E.read_iv(g2, ai3, cfg, "IV2", False, False, log)
o2 = g2.written["RR_READ/IV2.json"]
ok(o2.get("status") == "done" and o2.get("done_set") == "20261119_0859_early", "一番早いセット (11/19) で 完了")
ok(len(o2["sets"]) == 1 and ai3.calls == [12, 12] + [1] * 24, f"完了したら 残りのセット (11/20) は AI に出さない (セット · 枠 · 日付 1 枚ずつ 2 回 = 1 セット分だけ) → {len(ai3.calls)} 回")
ok(o2["sets"][0]["received"] == "2026-11-19" and o2["sets"][0]["undated"] == 12, "受信日 · 撮影日不明の枚数を記録")
ai4 = GoodAI()
ok(E.read_iv(g2, ai4, cfg, "IV2", False, False, log) is False and ai4.calls == [], "完了した IV は 翌日から読まない")
bad = {"sets": [{"photos": [], "sessions": {}}]}
ok(E.set_usable({"sessions": {"S1": {}}, "photos": [dict(rr_session="S1", rr_kind=k, rr_screen_ok=True, rr_sharp=0.5, rr_value=v, rr_value2=v)
    for k, v in [("bg", 0.1)] * 4 + [("m1", 0.1)] * 4 + [("sf", 0.35)] * 4]}) is None, "0.3 超え (不合格) のセットでは 完了にしない")
ok(E.received_date("20261119_0859_e554003a") == "2026-11-19" and E.received_date("x") == "", "セット名 → 受信日")


print("■ 7.0.1 答えの長さ (LTO 25 枚)")
ok(E.tokens_for(25, 350, 1500) == 10250 and E.tokens_for(12, 350, 1500) == 5700, "25 枚 → 10250 · 12 枚 → 5700 (以前は 4000 固定)")
ok(E.tokens_for(40, 350, 1500) == 15500 and E.tokens_for(100, 350, 1500) == 16000, "上限 16000")
class SizeAI(GoodAI):
    def __init__(self): super().__init__(); self.mt = []
    def ask(self, prompt, images, labels, max_tokens=4000):
        self.mt.append(max_tokens); return GoodAI.ask(self, prompt, images, labels, max_tokens)
g3, ai5 = Graph2(), SizeAI()
E.read_iv(g3, ai5, cfg, "IV2", False, False, log)
ok(ai5.mt[0] >= 350 * 12 and ai5.mt[1] >= 60 * 12, f"エンジンが 枚数に合わせて長さを渡す → {ai5.mt}")
class CutAI(FakeAI):
    def ask(self, *a, **k): raise RuntimeError("AI の答えが途中で切れました (max_tokens 1) — このセットは書きません")
g4 = Graph2()
ch4 = E.read_iv(g4, CutAI(), cfg, "IV2", False, False, log)
ok(ch4 is False and "RR_READ/IV2.json" not in g4.written, "答えが切れたら 何も書かない (おかしな結果を残さない)")


print("■ 7.0.2 2 回目は原寸から · 完了の記録 · 単価")
big = jpg(4000, 3000, seed=7)
_, small, full = E.prep_image(big, 1024, keep_full=True)
c_small = Image.open(io.BytesIO(E.crop_jpeg(small, [400, 400, 500, 450])))
c_full = Image.open(io.BytesIO(E.crop_jpeg(full, [400, 400, 500, 450])))
ok(full.size == (4000, 3000) and small.size == (1024, 768), "原寸 4000 と 縮小 1024 を両方持つ")
ok(c_full.width >= 800 and c_small.width >= 800, f"切り出しは 幅 800 以上に拡大 ({c_small.width} / {c_full.width})")
src_px = round(4000 * 0.13); ok(src_px > 400, f"原寸からの切り出しは 元の画素 {src_px}px (縮小からだと 約 {round(1024*0.13)}px)")
ok(abs(E.PRICE["in"] * 1e6 - 2.0) < 1e-9 and abs(E.PRICE["out"] * 1e6 - 10.0) < 1e-9, "単価 $2 / $10")
tmp = tempfile.mkdtemp(); c2 = {"data_dir": tmp}
E.save_done(c2, {"NAS2611-08"}); ok(E.load_done(c2) == {"NAS2611-08"}, "完了 IV を PC に記録 · 読み戻し")
class G5:
    def children(self, rel=None, item_id=None):
        return [{"name": "OLD2601-01", "folder": {}, "lastModifiedDateTime": "2026-01-01T00:00:00Z"}, {"name": "_actions", "folder": {}}]
ok(E.recent_ivs(G5(), {"photo_root": "PV2", "since_days": 0}) == ["OLD2601-01"], "since_days 0 → 古い IV フォルダも見る (_ で始まるものは除く)")


print("■ 7.0.3 表示どおり · 時刻 · 小数点 · 3 回目")
ok(E.disp_value("00.09", "μSv/h") == "0.09" and E.disp_value("0.130", "μSv/h") == "0.130" and E.disp_value("0.20", None) == "0.20", "表示どおり (00.09→0.09 · 0.130 · 0.20)")
ok(E.disp_value("0.1?", "μSv/h") is None and E.disp_value("0.13", "CPM") is None, "読めない · 単位違い → None")
ok(E.decimal_shift(0.045, 0.45) and E.decimal_shift(0.13, 13.0) and not E.decimal_shift(0.13, 0.15) and not E.decimal_shift(0.13, None), "10 倍 · 100 倍違い = 小数点の読み違い")
rr = E.finalize([{"file": "a.jpg", "taken": ""}, {"file": "b.jpg", "taken": ""}],
                [{"p": 1, "kind": "bg", "value": "0.20", "unit": "μSv/h", "stamp": "2026-11-19 14:27"},
                 {"p": 2, "kind": "bg", "value": "00.09", "unit": "μSv/h", "stamp": "2026-11-19"}], "20261119_0900_x")
ok(rr[0]["rr_value_disp"] == "0.20" and rr[1]["rr_value_disp"] == "0.09", "finalize: rr_value_disp")
ok(rr[0]["rr_stamp_time"] is True and rr[1]["rr_stamp_time"] is False, "写真の日付に 時刻あり / なし")
class AI3(FakeAI):
    """1 回目 0.045 ×12 · 2 回目 0.45 (小数点違い) と null · 3 回目 0.045"""
    def __init__(self): super().__init__(); self.n = 0
    def ask(self, prompt, images, labels, max_tokens=4000):
        self.calls.append(len(images)); self.n += 1
        if prompt.startswith("You are reading"):
            ks = ["bg"] * 4 + ["m1"] * 4 + ["sf"] * 4
            return {"photos": [{"p": i + 1, "session": "S1", "kind": ks[i], "value": "0.045", "unit": "μSv/h", "screen_on": True,
                                "box": [300, 300, 700, 600], "device": "X", "stamp": "2026-11-19"} for i in range(len(images))]}
        if self.n == 2:
            return {"values": [{"c": i + 1, "value": ("0.45" if i < 6 else (None if i < 9 else "0.045"))} for i in range(len(images))]}
        return {"values": [{"c": i + 1, "value": ("0.045" if i < 7 else None)} for i in range(len(images))]}
g6, ai6 = Graph2(), AI3()
g6.sets = {"20261119_0859_early": g6.sets["20261119_0859_early"]}
E.read_iv(g6, ai6, cfg, "IV2", False, False, log)
ph6 = g6.written["RR_READ/IV2.json"]["sets"][0]["photos"]
ok(ai6.calls == [12, 12, 9] + [1] * 24, f"AI (セット 12 · 枠 12 · 合わない 9 枚だけ 3 回目 · 日付 1 枚ずつ 2 回) → {len(ai6.calls)} 回")
ok(sum(1 for p in ph6 if "decimal" in p.get("rr_value2_note", "")) == 6, "10 倍の読み 6 枚 → 小数点の読み違いとして記録 (3 回目で直っても残る)")
ok(sum(1 for p in ph6 if p["rr_value2"] == 0.045) == 3 + 7 and sum(1 for p in ph6 if p["rr_value2"] is None) == 2, "3 回目で一致した 7 枚を採用 · 残り 2 枚は null (TOOL で 1 つずつ確認)")
ok(all(p["rr_value_disp"] == "0.045" for p in ph6), "表示どおり 0.045")


print("■ 7.0.4 写真の中の日付・時刻を もう一度読む")
ok(E.norm_time("8:52") == "08:52" and E.norm_time("16:14") == "16:14" and E.norm_time("25:00") == "" and E.norm_time(None) == "", "時刻を揃える (8:52 → 08:52)")
ok(E.stamp_crop_box({"_stamp_box": [700, 900, 990, 990]}) == [700, 900, 990, 990] and E.stamp_crop_box({}) == [0, 650, 1000, 1000], "日付の枠 · 無ければ 写真の下 35%")
class StampAI(GoodAI):
    """7.0.5: 1 枚ずつ 2 回 · n 回目の呼び出し = (n//2) 枚目
       0 枚目: 違う日付 · 1 枚目: 時刻なし · 3 枚目: 2 回の時刻が違う (8:53 / 8:58) · 他: 2026-11-19 08:5x"""
    def __init__(self): super().__init__(); self.k = 0
    def ask(self, prompt, images, labels, max_tokens=4000):
        if prompt.startswith("The image is a close crop of the date/time"):
            self.calls.append(len(images)); i = self.k // 2; second = self.k % 2; self.k += 1
            date = "2026-11-18" if i == 0 else "2026-11-19"
            time = None if i == 1 else (("8:58" if second else "8:53") if i == 3 else f"8:{50 + i % 10}")
            return {"date": date, "time": time}
        r = GoodAI.ask(self, prompt, images, labels, max_tokens)
        if prompt.startswith("You are reading"):
            for p in r["photos"]: p["stamp"] = "2026-11-19"; p["stamp_box"] = [700, 900, 990, 990]
        return r
g7, ai7 = Graph2(), StampAI()
g7.sets = {"20261119_0859_early": g7.sets["20261119_0859_early"]}
E.read_iv(g7, ai7, cfg, "IV2", False, False, log)
ph7 = g7.written["RR_READ/IV2.json"]["sets"][0]["photos"]
ok(ai7.calls[:2] == [12, 12] and ai7.calls[2:] == [1] * 24, f"日付・時刻は 1 枚ずつ 2 回 (12 × 2 = 24 回) → {len(ai7.calls[2:])} 回")
ok(ph7[3]["rr_taken"] == "2026-11-19" and ph7[3]["rr_stamp_time"] is False and ph7[3].get("rr_stamp_note") == "time 08:53/08:58", "2 回の時刻が違う (08:53 / 08:58) → 時刻は使わない · 記録だけ")
ok(len(set(p["rr_taken"] for p in ph7 if len(p["rr_taken"]) >= 16)) >= 8, "写真ごとに違う時刻を そのまま (全部同じに揃わない)")
ok(ph7[0]["rr_taken"] == "2026-11-19" and ph7[0]["rr_stamp_time"] is False, "読み直しの日付が 先の日付と違う → 使わない")
ok(ph7[1]["rr_taken"] == "2026-11-19" and ph7[1]["rr_stamp_time"] is False, "時刻が読めない → 日付だけ")
ok(ph7[2]["rr_taken"] == "2026-11-19 08:52" and ph7[2]["rr_stamp_time"] is True and ph7[2]["rr_taken_src"] == "stamp", "時刻を読めた → 2026-11-19 08:52 (src stamp)")
ok(all("_stamp_box" not in p for p in ph7), "作業用の枠は 結果に残さない")
g8 = FakeGraph(); ai8 = FakeAI()
E.read_iv(g8, ai8, cfg, "NAS2611-08", False, False, log)
ok(len(ai8.calls) == 3, f"EXIF に時刻がある写真ばかり → 日付の読み直しなし → {ai8.calls}")


print("■ 7.0.6 考える部分 (thinking) で答えが長くなる場合")
class ThinkAI(StampAI):
    """本物の Sonnet 5.5 のように 1 枚の日付読みに 600 トークン必要 · 上限が足りなければ 「切れました」"""
    def ask(self, prompt, images, labels, max_tokens=4000):
        if prompt.startswith("The image is a close crop of the date/time") and max_tokens < 600:
            raise RuntimeError(f"AI の答えが途中で切れました (max_tokens {max_tokens}) — このセットは書きません")
        return StampAI.ask(self, prompt, images, labels, max_tokens)
g9, ai9 = Graph2(), ThinkAI()
g9.sets = {"20261119_0859_early": g9.sets["20261119_0859_early"]}
E.read_iv(g9, ai9, cfg, "IV2", False, False, log)
ok("RR_READ/IV2.json" in g9.written, "1 枚 600 トークン必要でも セットを書ける (上限 1500)")
ok(E.STAMP_MAX_TOKENS >= 1000, f"日付・時刻の読みの上限 = {E.STAMP_MAX_TOKENS}")
class CutStampAI(StampAI):
    """日付読みだけ 毎回 切れる"""
    def ask(self, prompt, images, labels, max_tokens=4000):
        if prompt.startswith("The image is a close crop of the date/time"):
            raise RuntimeError("AI の答えが途中で切れました (max_tokens 1500) — このセットは書きません")
        return StampAI.ask(self, prompt, images, labels, max_tokens)
g10, ai10 = Graph2(), CutStampAI()
g10.sets = {"20261119_0859_early": g10.sets["20261119_0859_early"]}
E.read_iv(g10, ai10, cfg, "IV2", False, False, log)
o10 = g10.written.get("RR_READ/IV2.json")
ok(o10 is not None and all(p["rr_kind"] for p in o10["sets"][0]["photos"]), "日付読みが全部失敗しても セット (分類・数値) は捨てない")
ok(all(len(p["rr_taken"] or "") <= 10 for p in o10["sets"][0]["photos"]), "その場合 時刻は付けない (日付だけ)")
class CapAI(StampAI):
    def ask(self, prompt, images, labels, max_tokens=4000):
        if prompt.startswith("The image is a close crop of the date/time"):
            raise RuntimeError("今日の AI 費用の上限に達しました")
        return StampAI.ask(self, prompt, images, labels, max_tokens)
try:
    E.read_set(Graph2(), CapAI(), cfg, "20261119_0859_early", [{"name": f, "id": "J|20261119_0859_early|" + f, "size": 1, "eTag": "e"} for f in Graph2().sets["20261119_0859_early"]], log)
    ok(False, "費用上限は止める")
except RuntimeError as e:
    ok("上限" in str(e), "費用上限だけは そのまま止める")


print("■ 7.0.7 CUT 後 (▲ 書類作成中) にも _RR")
class GraphMoved(Graph2):
    """IV2 は ▲ 書類作成中 へ移動済み · PHOTO_V2 には無い"""
    def children(self, rel=None, item_id=None):
        if rel and rel.startswith("PV2/IV2"): return None
        if rel and rel.endswith("DOC/IV2/_RR"):
            return [{"name": n, "id": "S|" + n, "folder": {"childCount": 12}} for n in self.sets]
        if rel == "PV2": return [{"name": "NAS2611-08", "folder": {}}, {"name": "_data", "folder": {}}]
        if rel == "DOC": return [{"name": "IV2", "folder": {}}, {"name": "NAS2611-08", "folder": {}}, {"name": "_LEENAI", "folder": {}}]
        return Graph2.children(self, rel, item_id)
cfg2 = dict(cfg, doc_root="DOC", since_days=0)
gm, aim = GraphMoved(), GoodAI()
gm.sets = {"20261119_0859_early": gm.sets["20261119_0859_early"]}
ok(E.read_iv(gm, aim, cfg2, "IV2", False, False, log) and "RR_READ/IV2.json" in gm.written, "PHOTO_V2 に無い IV → ▲ 書類作成中 の _RR を読む")
ok(E.recent_ivs(gm, cfg2) == ["IV2", "NAS2611-08"], f"IV 一覧 = 2 か所の和 (重複 · _ で始まるものは除く) → {E.recent_ivs(gm, cfg2)}")
import tempfile as _tf, json as _js
p = _tf.mktemp(suffix=".json"); _js.dump({"tenant_id":"t","client_id":"c","drive_id":"d","photo_root":"古紙/-. 古紙書類/▲ LEENAI 通関作業中/PHOTO_V2","read_root":"r"}, open(p,"w",encoding="utf-8"))
ok(E.load_config(p)["doc_root"] == "古紙/-. 古紙書類/▲ 書類作成中", "doc_root を書かなければ photo_root から求める (古紙書類/▲ 書類作成中)")

print(f"\n結果: {P} OK · {F} NG")
sys.exit(1 if F else 0)
