# Thiết kế — Làm lại trang Chat ("Aurora Neon")

**Date:** 2026-06-16
**Competition:** Claw-a-thon 2026 · Track: Automation & Integration
**Scope:** Làm lại giao diện `ui/chat.html` cho sinh động/ấn tượng (ưu tiên demo & giám khảo), **không đổi hợp đồng backend**. Chỉ là một file tĩnh phía client.

---

## 1. Vấn đề & Giá trị

Trang chat hiện tại (`ui/chat.html`) hoạt động đầy đủ nhưng **thô sơ về thị giác**: bong bóng phẳng, màn chào là một khối chữ dài, panel cảnh báo là form dày đặc đẩy nội dung, không có "không khí" chuyển động. Với một sản phẩm dự thi, **ấn tượng đầu** và cảm giác "sống động" khi demo có giá trị cao.

**Mục tiêu:** nâng cấp trang thành giao diện cao cấp, có chuyển động, gây ấn tượng trong vài giây đầu — nhưng **gọn**, không cần onboarding dài, và **giữ nguyên mọi chức năng + hợp đồng API hiện có**.

**Đối tượng:** ưu tiên demo/giám khảo (hiệu ứng wow); vẫn dùng được như công cụ thật.

---

## 2. Ràng buộc (bất biến)

- **Một file duy nhất** `ui/chat.html`, vanilla HTML/CSS/JS, served tại `GET /` (xem `main.py`). **Không thêm bước build, không framework.**
- Được phép thêm **CDN nhẹ**: 1 font Google (vd Inter / Plus Jakarta Sans). Ưu tiên CSS thuần; chỉ thêm `anime.js` nếu thật cần (mặc định: không).
- **Không đổi backend.** Vẫn:
  - `POST /invocations` với header `X-GreenNode-AgentBase-Session-Id`, `X-GreenNode-AgentBase-User-Id`.
  - Body: `{message}` (chat thường) hoặc `{action, params}` với `action ∈ {hypothesis_check, manage_subscription}`.
  - Đọc `data.markdown` (render bằng marked.js) và `data.result.use_case` (lái charts/tables/suggestions).
- **Giữ trọn hành vi hiện có** (không được làm hỏng):
  - marked.js render markdown; Chart.js dựng biểu đồ qua `chartSpecs()` / `appendChart()` / `tableFor()` / `renderExtras()`.
  - Gating xuất CSV/JSON (chỉ hiện khi có bảng/biểu đồ hoặc khi user yêu cầu tải).
  - Enter an-toàn-IME (Tiếng Việt Telex/VNI) — Enter đang compose không gửi.
  - "Stickiness" của hypothesis checker (`hcActive` → route `action:'hypothesis_check'` khi đang giữa hội thoại).
  - Timeout cứng 180s + bộ đếm "Đang phân tích… Ns"; `AbortController`.
  - Toàn bộ ops đăng ký cảnh báo: `create | list | delete | test`, cùng các toggle `mode/freq/weekday/hour` và help (ⓘ).
  - `prefers-reduced-motion`: tôn trọng (tắt hiệu ứng động).

---

## 3. Hệ hình ảnh — "Aurora Neon"

Kết hợp: **nền aurora tối của hướng A** + **accent gradient/orb của hướng C** (đã chốt qua mockup).

| Token | Giá trị (dự kiến, tinh chỉnh khi code) |
|---|---|
| Nền nền | `#0a0e16` (đậm hơn `#0f1117` hiện tại) |
| Aurora | 2–3 vệt radial-gradient mờ (blur ~60px): xanh-lá `#22c55e`, cyan `#22d3ee`, tím `#a855f7` — trôi chậm 14–18s |
| Accent chính | xanh-lá `#22c55e` (giữ brand) |
| Gradient accent | `linear-gradient(135deg,#22c55e,#22d3ee,#a855f7)` |
| Bong bóng bot | kính mờ: nền `rgba(255,255,255,.05)` + viền `rgba(148,163,184,.18)` + `backdrop-filter:blur(6px)` |
| Bong bóng user | `linear-gradient(135deg,#1e3a5f,#1e4f6e)` |
| Avatar bot | orb `conic-gradient` xoay + quầng glow (glyph `✦`) |
| Avatar user | ô bo góc, nền `linear-gradient(135deg,#1e3a5f,#2563eb)`, **SVG line người** (phương án A) — thay emoji 🧑 |
| Wordmark | "Veridex" tô gradient (`background-clip:text`) |
| Font | 1 font Google sans (Inter / Plus Jakarta Sans) |

---

## 4. Bố cục & thành phần

### 4.1 Header
Orb nhỏ + **wordmark gradient "Veridex"** + chấm trạng thái "live" nhấp nháy + nút **🔔 Cảnh báo** (viền gradient) + subtitle bên phải ("App & game · App Store & Google Play · VI/EN").

### 4.2 Màn chào = **Hero rỗng** (thay khối chữ dài)
- Hiển thị khi **chưa có tin nhắn nào**, nằm trong vùng `#messages`.
- Gồm: **orb lớn nổi bồng bềnh**, tiêu đề gradient "Veridex", tagline ngắn, **4 thẻ ví dụ "bấm-là-hỏi"** (Review · So sánh · Bất thường · Cảnh báo) — click = đổ prompt vào ô nhập và `send()`.
- **Thanh nhập luôn hiển thị ở dưới** (footer cố định) — user gõ tự do bất cứ lúc nào.
- Gửi tin đầu tiên → hero **ẩn/đẩy lên**, vào luồng chat bình thường. (Hero chỉ là một node trong `#messages`, bị xoá khi tin user đầu tiên được thêm.)

### 4.3 Vùng tin nhắn
- Bong bóng bot (kính mờ) / user (gradient xanh) như §3; avatar mới.
- **Nút copy** trên tin bot: hover hiện, copy markdown gốc của tin đó.
- **Chip gợi ý theo ngữ cảnh** sau câu trả lời: tái sử dụng cơ chế `renderSuggestions()` sẵn có, chỉ làm đẹp (viền gradient).
- **Nút "↓ mới nhất"**: hiện khi user cuộn lên (không ở đáy), click cuộn về cuối.

### 4.4 Panel cảnh báo = **Drawer trượt từ phải**
- Click 🔔 → drawer overlay trượt vào từ mép phải + lớp mờ nền (backdrop). **Không đẩy** nội dung chat.
- Đóng bằng: nút ✕, click backdrop, hoặc phím **ESC**.
- **Giữ nguyên toàn bộ form + logic** đăng ký hiện có (`subSave/subTest/subList/subDelete`, toggle mode/freq/weekday/hour, help ⓘ) — chỉ tái bố trí vào drawer.

### 4.5 Footer
Textarea (auto-grow giữ nguyên hành vi) + **nút gửi gradient**. Trạng thái disabled khi đang gửi.

---

## 5. Chuyển động (mức "đầy đủ — wow")

1. **Nền aurora** trôi chậm (CSS keyframes transform/scale).
2. **Orb bot** xoay + quầng glow; orb hero nổi bồng bềnh (float).
3. **Tin nhắn trượt vào** (fadeInUp) khi xuất hiện.
4. **Typing dots** 3 chấm nảy trong lúc chờ phản hồi (thay text "Đang phân tích…", nhưng vẫn giữ bộ đếm giây cho phản hồi lâu).
5. **Bot trả lời hiện dần kiểu "đang gõ" (typewriter mô phỏng).**
   > ⚠️ Backend trả **một lần** (không SSE/streaming). Đây là hiệu ứng front-end trên nội dung **đã nhận đủ**. Cách an toàn để không vỡ markdown/bảng/biểu đồ: parse markdown đầy đủ trước, rồi **reveal khối đã render** (fade/slide theo từng đoạn hoặc theo từng từ bằng CSS). **Charts/bảng/chip/export được append SAU khi reveal xong.** Nếu typewriter gây phức tạp/giật, fallback = fade+slide mượt của cả khối (vẫn "sống").
6. **Biểu đồ vẽ dần**: bật animation Chart.js (bỏ `animation:false` hiện tại), giữ màu accent.
7. **Drawer**: trượt + backdrop fade.
8. **Toast**: trượt lên góc khi lưu/test/lỗi đăng ký.
9. **`prefers-reduced-motion: reduce`**: tắt aurora, orb-spin/float, typewriter, chart-animation → về fade tối giản. (Mở rộng khối `@media` đã có.)

---

## 6. Điểm nhấn thêm (đã chốt)

- **Nút copy** trên tin bot (hover).
- **Chip gợi ý theo ngữ cảnh** — làm đẹp cơ chế `suggestions` sẵn có.
- **Toast trạng thái** cho luồng đăng ký (lưu/test/xoá/lỗi) thay dòng `#subStatus` tĩnh — **giữ `#subStatus` làm fallback/aria-live** để không mất thông tin lỗi.
- **Nút cuộn xuống cuối** ("↓ mới nhất").

---

## 7. Khả dụng & hiệu năng

- Tương phản chữ/nền đạt mức đọc tốt trên nền tối.
- Drawer: quản lý focus hợp lý, đóng bằng ESC + backdrop; `aria-label` cho nút copy/gửi/đóng.
- Toast & status dùng `aria-live="polite"`.
- Mọi animation dùng **CSS transform/opacity** (rẻ, không reflow); không thêm dependency nặng. Aurora/orb dùng `will-change` thận trọng.
- Không phá luồng IME tiếng Việt; không chặn paste.

---

## 8. Kiểm thử & nghiệm thu

Đây là **file tĩnh client; backend không đổi** → **không thêm unit test CI** (pytest/ruff không phủ HTML). Nghiệm thu bằng tay:

1. `python main.py` → mở `GET /` (http://0.0.0.0:8080).
2. **Hero**: tải trang thấy hero + thẻ ví dụ; click thẻ → gửi đúng prompt; gõ tay vẫn được; gửi tin đầu → hero ẩn.
3. **Chat thường**: hỏi một app → có markdown, biểu đồ vẽ dần, chip gợi ý, nút copy hoạt động, export CSV/JSON hiện đúng điều kiện.
4. **Hypothesis multi-turn**: nêu giả thuyết → hỏi lại nhiều lượt (kiểm `hcActive` vẫn route đúng).
5. **Drawer cảnh báo**: mở/đóng (✕/backdrop/ESC); `create/list/delete/test` chạy; toast hiện; toggle mode (alert ẩn giờ, digest hiện giờ/tần suất/thứ) đúng.
6. **Reduced motion**: bật "Reduce motion" của OS → aurora/orb/typewriter tắt, vẫn dùng được.
7. **IME**: gõ tiếng Việt Telex — Enter giữa lúc compose không gửi.
8. **Timeout/đếm giây**: phản hồi lâu vẫn thấy đếm giây; quá 180s ra thông báo timeout.

---

## 9. Ngoài phạm vi (YAGNI)

- Không streaming thật (SSE) từ backend.
- Không thêm framework/bundler; không tách nhiều file.
- Không đổi logic định tuyến/use case/connector.
- Không thêm âm thanh; không đa theme sáng/tối (chỉ tinh chỉnh trong hướng Aurora Neon).
