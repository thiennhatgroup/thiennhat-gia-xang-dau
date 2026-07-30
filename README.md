# Giá xăng dầu Việt Nam — dữ liệu tự động

Lấy bảng giá bán lẻ chính thống của **Petrolimex** mỗi kỳ điều hành và xuất ra
JSON để hệ thống khác đọc.

## Vì sao repo này tồn tại

Bot bản tin xăng dầu chạy trên Google Apps Script. Đo thực tế cho thấy
`petrolimex.com.vn` và `files.petrolimex.com.vn` **chặn dải IP của Google** —
Apps Script trả `Address unavailable` và treo khoảng 256 giây mỗi lần gọi.

Máy chủ GitHub đặt ở Mỹ và vào được bình thường, nên phần crawl chuyển sang
GitHub Actions. Apps Script chỉ việc đọc file JSON ở đây.

## Dữ liệu

`data/gia-xang-dau.json` — cập nhật tự động, đọc trực tiếp qua:

```
https://raw.githubusercontent.com/thiennhatgroup/thiennhat-gia-xang-dau/main/data/gia-xang-dau.json
```

Gồm 8 mặt hàng × Vùng 1 và Vùng 2: xăng E10 RON 95-V, E10 RON 95-III,
E5 RON 92-II, Điêzen 0,001S-V, Điêzen 0,05S-II, dầu hỏa 2-K và hai loại mazút.

## Cách bảo đảm số đúng

Bảng giá Petrolimex công bố dưới dạng **ảnh**, nên phải OCR. Để OCR đọc sai
không lọt ra ngoài:

1. OCR ảnh ra đủ 8 mặt hàng.
2. Đối chiếu với `webgia.com` — trang này có 4 trong 8 mặt hàng.
3. Bốn dòng đó phải **khớp tuyệt đối**. Khớp thì chứng tỏ OCR đọc đúng ảnh,
   nên 4 dòng còn lại (RON 95, mazút) cũng tin được.
4. Lệch một chữ số thôi cũng chuyển `trang_thai` sang `LECH`, **giữ nguyên số
   cũ** và không xuất bản số mới.

Nguyên tắc: thà số cũ còn hơn số sai.

## Trạng thái trong JSON

| Giá trị | Nghĩa |
| --- | --- |
| `OK` | OCR đọc được và khớp đối chiếu — dùng được |
| `LECH` | OCR lệch so với webgia — giữ số cũ, cần xem lại |
| `THIEU` | OCR không đọc đủ mặt hàng |
| `FAIL` | không lấy được trang hoặc ảnh |

## Lịch chạy

15:20, 17:00 và 08:00 giờ Việt Nam. Kỳ điều hành thường có hiệu lực 15:00.

## Không dùng PVOil

PVOil chặn bằng thử thách chống bot của Cloudflare, từ cả IP Việt Nam lẫn Mỹ.
Vượt qua cơ chế đó là né hệ thống phát hiện bot nên repo này không làm.
Petrolimex không có Cloudflare.
