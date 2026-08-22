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

import io, json, os, re, subprocess, sys, tempfile, datetime
import urllib.request, urllib.parse

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


# Ảnh trong bài nằm ở files.petrolimex.com.vn/jpgs/<hash>/<hash>/<tên>.jpg
# Tên ảnh KHÔNG cố định: tới kỳ 23/07/2026 vẫn là gbl.jpg (bảng giá) và
# trich.jpg (trích lập Quỹ BOG), từ kỳ 20/08/2026 đổi sang dấu thời gian
# ("20-08-2026 14-40-51.jpg", trong HTML là %20). Ghim cứng gbl.jpg làm crawler
# chết âm thầm suốt hai kỳ. Thứ tự thì không đổi: ảnh bảng giá LUÔN đứng trước.
#
# Quét theo giá trị thuộc tính có dấu nháy (src/href/srcset/data-src) chứ không
# quét URL trần: tên ảnh có thể chứa dấu cách chưa mã hoá, mà dừng ở dấu nháy
# thì vẫn lấy trọn. Neo cuối chuỗi bằng \Z để bỏ biến thể .jpg.webp mà
# <source srcset> chèn ngay trước ảnh thật.
RE_THUOC_TINH = re.compile(
    r"""(?:src|srcset|href|data-src)\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.I)
RE_ANH_JPGS = re.compile(
    r"""(?:https?:)?//files\.petrolimex\.com\.vn/jpgs/.+\.jpe?g\Z""", re.I)


def anh_bang_gia(url):
    """URL ảnh bảng giá trong bài.

    Lấy ảnh /jpgs/ ĐẦU TIÊN theo thứ tự xuất hiện, ưu tiên gbl.jpg nếu bài cũ
    còn dùng tên đó. Lấy nhầm ảnh Quỹ BOG cũng không đăng sai được: mỏ neo E5 ở
    main() sẽ không khớp và cả kỳ bị từ chối.
    """
    html = get(url)
    thay = []
    for m in RE_THUOC_TINH.finditer(html):
        u = (m.group(1) or m.group(2)).strip()
        if RE_ANH_JPGS.match(u) and u not in thay:
            thay.append(u)
    if not thay:
        raise RuntimeError("Không thấy ảnh nào trong /jpgs/ của bài")
    u = next((x for x in thay if x.lower().endswith("/gbl.jpg")), thay[0])
    if not u.startswith("http"):
        u = "https:" + u
    # %20 đã có sẵn thì giữ nguyên (dấu % nằm trong safe), dấu cách thô thì mã
    # hoá nốt — urllib.request không nuốt được dấu cách trần.
    return urllib.parse.quote(u, safe=":/%?&=#")


def ocr(img_bytes):
    """Tiền xử lý rồi OCR.

    Ảnh gốc chỉ 966x554 — quá nhỏ, tesseract đọc sai tên mặt hàng (95-V thành
    98V), mất dấu chấm nghìn, và BỎ HẲN hai dòng Điêzen. Phóng to 3 lần + xám +
    tăng tương phản khắc phục phần lớn.
    """
    from PIL import Image, ImageOps
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "g.png")
        im = Image.open(io.BytesIO(img_bytes)).convert("L")
        im = im.resize((im.width * 3, im.height * 3), Image.LANCZOS)
        im = ImageOps.autocontrast(im)
        im.save(src)
        r = subprocess.run(
            ["tesseract", src, "stdout", "-l", "vie+eng", "--psm", "6"],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("tesseract lỗi: " + r.stderr[:300])
        return r.stdout


def so_trong_dong(line):
    """Các số tiền trong một dòng. Chấp nhận cả 22.830 lẫn 22830 vì OCR hay
    nuốt mất dấu chấm nghìn."""
    out = []
    for m in re.finditer(r"\b\d{2}\s*[.,]?\s*\d{3}\b", line):
        v = int(re.sub(r"[^\d]", "", m.group(0)))
        if 9000 < v < 90000:
            out.append(v)
    return out


def doc_bang(txt):
    """Lấy 8 dòng giá THEO THỨ TỰ, không dựa vào tên mặt hàng.

    OCR đọc sai tên (95-V -> 98V, 95-III -> 96-II) nên khớp theo tên là không
    đáng tin. Nhưng thứ tự 8 mặt hàng trong bảng Petrolimex cố định nhiều năm,
    và mỗi dòng giá có đúng 2 số tiền. Nên: lọc các dòng có >= 2 số tiền, rồi
    gán theo thứ tự. Nếu không ra đúng 8 dòng thì coi như thất bại — đối chiếu
    webgia phía sau sẽ bắt được mọi trường hợp lệch hàng.
    """
    rows = []
    for line in txt.splitlines():
        so = so_trong_dong(line)
        if len(so) >= 2:
            rows.append(so[:2])
    return rows


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


def ky_cua_gia(d):
    """Kỳ mà phần `gia` của một file kết quả THẬT SỰ thuộc về.

    File cũ có thể do bản trước bản vá này ghi ra, khi đó `ky` là kỳ của BÀI chứ
    chưa chắc là kỳ của giá — nên phải suy ngược theo trạng thái.
    """
    if d.get("ky_cua_gia"):
        return d["ky_cua_gia"]
    if d.get("trang_thai") in ("OK", "THIEU_R95"):
        return d.get("ky")
    return d.get("giu_so_cu_tu") or d.get("ky")


def main():
    """Chiến lược sau 3 vòng thử OCR trên ảnh thật:

    tesseract KHÔNG đọc nổi ảnh này một cách trọn vẹn — hai dòng Điêzen biến
    mất qua mọi cấu hình đã thử, và mazút bị đọc sai chữ số (20.360 -> 204360,
    15.870 -> 18.870). Nhưng hai dòng RON 95 thì đọc ĐÚNG ở cả hai lần chạy.

    Nên chia việc theo đúng chỗ mạnh của từng nguồn:
      · 4 mặt hàng webgia có (E5, Điêzen 0,001S, Điêzen 0,05S, dầu hỏa)
        -> lấy THẲNG từ webgia, đã xác minh khớp bảng chính thống
      · 2 dòng RON 95 (webgia bỏ trống vì đổi tên sang E10)
        -> lấy từ OCR, dùng dòng E5 làm MỎ NEO để chứng minh không lệch hàng
      · mazút -> bỏ, không ai dùng và OCR không đáng tin ở đó

    Mỏ neo: tìm dòng OCR có cặp số trùng KHỚP TUYỆT ĐỐI với E5 của webgia.
    Trong bảng Petrolimex, ngay phía trên E5 luôn là RON 95-III rồi RON 95-V.
    Neo khớp nghĩa là OCR đọc đúng ảnh đó và hàng không xê dịch.
    """
    kq = {
        "cap_nhat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # `ky` LUÔN là kỳ mà phần `gia` thuộc về — kể cả khi đang giữ số cũ.
        # Kỳ của bài mới nhất nằm riêng ở `ky_bai_moi_nhat`. Gộp hai mốc này
        # vào một trường là cách bản cũ dán nhãn kỳ 20/08 lên giá kỳ 23/07.
        "trang_thai": "FAIL", "ky": None, "ky_cua_gia": None,
        "ky_bai_moi_nhat": None, "gio_hieu_luc": None,
        "nguon": "webgia + OCR Petrolimex (neo E5)", "gia": {}, "loi": [], "doi_chieu": {},
    }
    try:
        d, url, gio = ky_moi_nhat()
        kq["ky_bai_moi_nhat"] = d.strftime("%d/%m/%Y")
        kq["ky"] = kq["ky_bai_moi_nhat"]   # tạm; cuối hàm sẽ chốt lại theo `gia`
        kq["gio_hieu_luc"] = gio
        kq["bai"] = url

        wg = doc_webgia()
        if not wg.get("E5_R92"):
            raise RuntimeError("webgia không có E5 — không có mỏ neo để kiểm OCR")

        gia = {}
        for k, ten, _, re_wg in SP:
            if re_wg and k in wg:
                gia[k] = {"ten": ten, "v1": wg[k]["v1"], "v2": wg[k]["v2"], "nguon": "webgia"}

        # --- OCR chỉ để lấy 2 dòng RON 95 ---
        img_url = anh_bang_gia(url)
        kq["anh"] = img_url
        raw = ocr(get(img_url, binary=True))
        rows = doc_bang(raw)
        kq["so_dong_ocr"] = len(rows)

        e5 = wg["E5_R92"]
        neo = -1
        for idx, r in enumerate(rows):
            if r[0] == e5["v1"] and (not e5["v2"] or r[1] == e5["v2"]):
                neo = idx
                break

        # webgia có ĐỒNG BỘ với kỳ đang xét không?
        # Ảnh Petrolimex là của kỳ MỚI. Nếu OCR đọc được các dòng giá mà KHÔNG
        # dòng nào trùng E5 của webgia, thì webgia còn đang ở kỳ CŨ (nó cập nhật
        # chậm hơn Petrolimex vài chục phút). Đăng giá cũ dưới nhãn kỳ mới là
        # sai nghiêm trọng -> không đăng gì, giữ số cũ.
        if rows and neo < 0:
            kq["trang_thai"] = "LECH_NGUON"
            kq["loi"].append(
                f"OCR đọc được {len(rows)} dòng nhưng không dòng nào trùng E5 webgia "
                f"({e5['v1']}/{e5['v2']}) — webgia có thể còn ở kỳ cũ. Không đăng.")
            kq["gia"] = {}
        elif not rows:
            kq["loi"].append("OCR không đọc được dòng nào — 4 mặt hàng webgia "
                             "chưa được đối chiếu với kỳ này")

        if neo >= 2:
            r3, r5 = rows[neo - 1], rows[neo - 2]
            if not (r5[0] > r3[0] > e5["v1"]):
                kq["loi"].append(
                    f"RON95 sai thứ bậc giá (V={r5[0]}, III={r3[0]}, E5={e5['v1']}) — bỏ qua")
            else:
                gia["E10_R95_III"] = {"ten": "Xăng E10 RON 95-III", "v1": r3[0], "v2": r3[1],
                                      "nguon": "OCR Petrolimex (neo E5)"}
                gia["E10_R95_V"] = {"ten": "Xăng E10 RON 95-V", "v1": r5[0], "v2": r5[1],
                                    "nguon": "OCR Petrolimex (neo E5)"}
                kq["doi_chieu"]["neo_E5"] = {"dong_ocr": neo, "ocr": rows[neo],
                                             "webgia": [e5["v1"], e5["v2"]], "khop": True}
        elif rows:
            kq["loi"].append(f"Neo E5 ở dòng {neo}, không đủ 2 dòng phía trên cho RON 95")

        co_r95 = "E10_R95_III" in gia
        if kq["trang_thai"] == "LECH_NGUON":
            pass
        elif len(gia) >= 4 and co_r95:
            kq["trang_thai"] = "OK"
        elif len(gia) >= 4:
            kq["trang_thai"] = "THIEU_R95"      # vẫn dùng được: đủ xăng E5 + 2 loại điêzen
        else:
            kq["trang_thai"] = "THIEU"
        kq["gia"] = gia

    except Exception as e:
        kq["loi"].append(str(e))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    # Giữ số cũ khi thất bại là đúng — "thà số cũ hơn số sai". Nhưng số cũ phải
    # mang đúng NHÃN cũ. Bản trước ghi `ky` là kỳ của bài mới nhất trong khi
    # `gia` vẫn là của kỳ trước đó, nên ai đọc JSON cũng hiểu nhầm giá cũ là
    # giá kỳ mới. Ở đây `ky` luôn đi kèm `gia`.
    if kq["gia"]:
        kq["ky_cua_gia"] = kq["ky"]
    elif os.path.exists(OUT):
        try:
            cu = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            cu = {}
        if cu.get("gia"):
            ky_cu = ky_cua_gia(cu)
            kq["gia"] = cu["gia"]
            kq["ky"] = ky_cu
            kq["ky_cua_gia"] = ky_cu
            kq["gio_hieu_luc"] = cu.get("gio_hieu_luc")
            kq["giu_so_cu_tu"] = ky_cu
            if ky_cu != kq["ky_bai_moi_nhat"]:
                kq["loi"].append(
                    f"Giữ nguyên giá kỳ {ky_cu}; kỳ {kq['ky_bai_moi_nhat']} chưa lấy được.")
            else:
                kq["loi"].append(f"Giữ nguyên giá kỳ {ky_cu} của lần chạy trước.")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(kq, f, ensure_ascii=False, indent=1)

    print(json.dumps({"trang_thai": kq["trang_thai"], "ky_cua_gia": kq["ky"],
                      "ky_bai_moi_nhat": kq["ky_bai_moi_nhat"],
                      "so_mat_hang": len(kq["gia"]),
                      "mat_hang": sorted(kq["gia"].keys()), "loi": kq["loi"]},
                     ensure_ascii=False, indent=1))
    return 0 if kq["trang_thai"] in ("OK", "THIEU_R95") else 1


if __name__ == "__main__":
    sys.exit(main())
