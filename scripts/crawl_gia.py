#!/usr/bin/env python3
"""
crawl_gia.py — lấy bảng giá xăng dầu chính thống của Petrolimex.

VÌ SAO CHẠY Ở GITHUB ACTIONS CHỨ KHÔNG PHẢI APPS SCRIPT:
  Đo thực tế từ Apps Script: petrolimex.com.vn và files.petrolimex.com.vn đều
  trả "Address unavailable" và treo ~256 giây — Petrolimex chặn dải IP Google.
  Từ máy chủ Mỹ thì vào bình thường, và GitHub runner nằm ở Mỹ.

  PVOil KHÔNG dùng: nó chặn bằng thử thách chống bot của Cloudflare.

ĐƯỜNG ĐI:
  1. Trang thông cáo báo chí -> bài điều chỉnh giá mới nhất
  2. Trong bài -> ảnh bảng giá gbl.jpg
  3. OCR ảnh -> 8 mặt hàng x Vùng 1, Vùng 2
  4. ĐỐI CHIẾU với webgia: 4 mặt hàng webgia có phải khớp TUYỆT ĐỐI.
     Đây là cách tự kiểm OCR — nếu OCR đọc sai một chữ số thì 4 dòng đó lệch
     và ta biết ngay, kể cả với 4 dòng webgia không có (RON 95, mazút).
  5. Ghi data/gia-xang-dau.json để Apps Script đọc qua raw.githubusercontent.com
     (Google vào GitHub được, nên không cần service account).

  OCR fail hoặc đối chiếu lệch -> GIỮ NGUYÊN file cũ, ghi trạng thái lỗi.
  Nguyên tắc: thà số cũ còn hơn số sai.
"""

import json, os, re, subprocess, sys, tempfile, datetime, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
TCBC = "https://www.petrolimex.com.vn/ndi/thong-cao-bao-chi.html"
BASE = "https://www.petrolimex.com.vn"
WEBGIA = "https://webgia.com/gia-xang-dau/petrolimex/"
OUT = "data/gia-xang-dau.json"

# 8 mặt hàng theo đúng tên Petrolimex công bố.
# wg = mẫu nhận dạng trên webgia (None = webgia không có -> không đối chiếu được)
SP = [
    ("E10_R95_V",   "Xăng E10 RON 95-V",    r"E10\s*RON\s*95\s*-?\s*V\b",  None),
    ("E10_R95_III", "Xăng E10 RON 95-III",  r"E10\s*RON\s*95\s*-?\s*III",  None),
    ("E5_R92",      "Xăng E5 RON 92-II",    r"E5\s*RON\s*92",              r"E5\s*RON\s*92"),
    ("DO_0001S",    "Điêzen 0,001S-V",      r"0\s*[.,]\s*001\s*S",         r"0,001S"),
    ("DO_005S",     "Điêzen 0,05S-II",      r"0\s*[.,]\s*05\s*S",          r"0,05S"),
    ("KERO",        "Dầu hỏa 2-K",          r"[Dd]ầu\s*hỏa|hoa\s*2",       r"hỏa"),
    ("FO35",        "Mazút N2B 3,5S",       r"N\s*0?\s*2B",                None),
    ("FO180",       "Mazút 180cst 0,5S",    r"180\s*cst",                  None),
]


def get(url, binary=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = r.read()
    return d if binary else d.decode("utf-8", "replace")


def soc(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s.replace("&nbsp;", " "))


def ky_moi_nhat():
    """Bài điều chỉnh giá mới nhất. URL không đoán được (kỳ 02/7 là '16 giờ',
    kỳ 01/7 là '00 giờ') nên bắt buộc đọc trang danh sách."""
    html = get(TCBC)
    best = None
    for m in re.finditer(
        r'href="(/ndi/thong-cao-bao-chi/petrolimex-dieu-chinh-gia-xang-dau[^"]*?'
        r'ngay-(\d{1,2})-(\d{1,2})-(\d{4})\.html)"', html, re.I):
        d = datetime.date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        if not best or d > best[0]:
            g = re.search(r"tu-(\d{1,2})-gio-(\d{1,2})-phut", m.group(1))
            best = (d, BASE + m.group(1), f"{g.group(1)}:{g.group(2)}" if g else "15:00")
    if not best:
        raise RuntimeError("Không thấy bài điều chỉnh giá nào")
    return best


def anh_bang_gia(url):
    html = get(url)
    m = re.search(r'src="((?:https?:)?//files\.petrolimex\.com\.vn/[^"]*gbl\.jpg)"',
                  html, re.I)
    if not m:
        raise RuntimeError("Không thấy ảnh gbl.jpg trong bài")
    u = m.group(1)
    return u if u.startswith("http") else "https:" + u


def ocr(img_bytes):
    """tesseract, cài sẵn trong workflow. --psm 6 = coi ảnh là một khối văn bản."""
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "g.jpg")
        open(p, "wb").write(img_bytes)
        r = subprocess.run(
            ["tesseract", p, "stdout", "-l", "vie+eng", "--psm", "6"],
            capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise RuntimeError("tesseract lỗi: " + r.stderr[:300])
        return r.stdout


def hai_so(txt, pattern):
    """Hai số dạng 22.830 xuất hiện ngay sau tên mặt hàng."""
    m = re.search(pattern, txt, re.I)
    if not m:
        return None
    sau = txt[m.start(): m.start() + 240]
    so = [int(x.replace(".", "").replace(",", "").replace(" ", ""))
          for x in re.findall(r"\b\d{2}\s*[.,]\s*\d{3}\b", sau)]
    so = [v for v in so if 9000 < v < 90000]
    if not so:
        return None
    return {"v1": so[0], "v2": so[1] if len(so) > 1 else None}


def doc_webgia():
    html = get(WEBGIA)
    tb = re.search(r"<table[\s\S]*?</table>", html, re.I)
    out = {}
    if not tb:
        return out
    for tr in re.findall(r"<tr[\s\S]*?</tr>", tb.group(0), re.I):
        t = soc(tr)
        for k, _ten, _re_ocr, re_wg in SP:
            if not re_wg or k in out or not re.search(re_wg, t, re.I):
                continue
            r = hai_so(t, re_wg)
            if r:
                out[k] = r
    return out


def main():
    kq = {
        "cap_nhat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "trang_thai": "FAIL", "ky": None, "gio_hieu_luc": None,
        "nguon": "petrolimex-tcbc-ocr", "gia": {}, "loi": [], "doi_chieu": {},
    }
    try:
        d, url, gio = ky_moi_nhat()
        kq["ky"] = d.strftime("%d/%m/%Y")
        kq["gio_hieu_luc"] = gio
        kq["bai"] = url

        img_url = anh_bang_gia(url)
        kq["anh"] = img_url
        raw = ocr(get(img_url, binary=True))
        txt = soc(raw)
        kq["ocr_raw"] = raw[:3000]
        print("=" * 20, "VĂN BẢN OCR THÔ", "=" * 20)
        print(raw[:3000])
        print("=" * 20, "SAU KHI CHUẨN HOÁ", "=" * 20)
        print(txt[:2000])
        print("=" * 58)

        gia = {}
        for k, ten, re_ocr, _ in SP:
            r = hai_so(txt, re_ocr)
            if r:
                gia[k] = {"ten": ten, "v1": r["v1"], "v2": r["v2"]}
            else:
                kq["loi"].append(f"OCR không đọc được {ten}")

        # --- đối chiếu webgia: đây là cách tự kiểm OCR ---
        wg = {}
        try:
            wg = doc_webgia()
        except Exception as e:
            kq["loi"].append(f"webgia lỗi (không chặn): {e}")

        khop = lech = 0
        for k, ten, _, re_wg in SP:
            if not re_wg or k not in gia or k not in wg:
                continue
            a, b = gia[k], wg[k]
            ok = a["v1"] == b["v1"] and (not a["v2"] or not b["v2"] or a["v2"] == b["v2"])
            kq["doi_chieu"][k] = {"ocr": [a["v1"], a["v2"]],
                                  "webgia": [b["v1"], b["v2"]], "khop": ok}
            khop += ok
            lech += (not ok)
            if not ok:
                kq["loi"].append(
                    f"{ten}: OCR {a['v1']}/{a['v2']} khác webgia {b['v1']}/{b['v2']}")

        if lech:
            # OCR sai ở dòng kiểm được -> không tin cả bảng. Giữ file cũ.
            kq["trang_thai"] = "LECH"
        elif khop >= 2 and len(gia) >= 6:
            kq["trang_thai"] = "OK"
            kq["gia"] = gia
        else:
            kq["trang_thai"] = "THIEU"
            kq["loi"].append(f"chỉ đối chiếu được {khop} dòng, OCR ra {len(gia)}/8 mặt hàng")

    except Exception as e:
        kq["loi"].append(str(e))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if kq["trang_thai"] != "OK" and os.path.exists(OUT):
        try:
            cu = json.load(open(OUT, encoding="utf-8"))
            kq["gia"] = cu.get("gia", {})
            kq["giu_so_cu_tu"] = cu.get("ky")
        except Exception:
            pass

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(kq, f, ensure_ascii=False, indent=1)

    print(json.dumps({"trang_thai": kq["trang_thai"], "ky": kq["ky"],
                      "so_mat_hang": len(kq["gia"]), "loi": kq["loi"]},
                     ensure_ascii=False, indent=1))
    return 0 if kq["trang_thai"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
