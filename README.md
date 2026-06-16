# Veridex — App Intelligence Agent

> Claw-a-thon 2026 · Hạng mục: **Automation & Integration** · Nền tảng: **GreenNode AgentBase**

**Veridex** ("veritas" + "index" — *chỉ mục sự thật từ tín hiệu app-store*) là một AI agent biến các
**tín hiệu công khai trên App Store / Google Play** — cho cả ứng dụng **và** game (metadata, điểm số,
đánh giá, thứ hạng, lịch sử phiên bản) — thành **quyết định sản phẩm dựa trên bằng chứng**, trong vài
phút thay vì vài giờ. Agent trả lời bằng ngôn ngữ tự nhiên (tiếng Việt hoặc tiếng Anh), trình bày rõ
cách nó suy luận, và luôn trung thực về điều nó chứng minh được và không chứng minh được.

Bạn có thể trò chuyện với agent qua **giao diện chat web tích hợp sẵn** hoặc gọi nó như một HTTP API.

---

## 1. Bài toán (Problem)

Product Manager và lãnh đạo liên tục đưa ra nhận định về một bản phát hành hay một thị trường —
*"bản build mới làm tụt rating"*, *"người dùng ghét bản cập nhật mới nhất"*, *"đối thủ X đang thắng ở Y"* —
nhưng **việc kiểm chứng bất kỳ nhận định nào cũng chậm, thủ công và thiếu nhất quán**:

- Chỉ số trên store nằm rải rác giữa **iOS và Android**, ở các định dạng khác nhau.
- Đọc đủ số lượng review để thấy một xu hướng thực sự tốn hàng giờ, và việc so sánh "trước vs sau"
  một bản phát hành phải làm thủ công.
- **Không có lịch sử**: app store chỉ hiển thị số liệu hôm nay, không cho biết rating/thứ hạng đã biến
  động ra sao theo thời gian.
- Nhận định cảm tính bị đem ra hành động mà không kiểm tra dữ liệu có thực sự ủng hộ hay không — và
  không phân biệt được *tương quan* (correlation) với *nhân quả* (causation).

Hệ quả là quyết định dựa trên ý kiến và giai thoại thay vì bằng chứng.

---

## 2. Người dùng (Users)

| Người dùng | Veridex mang lại gì |
|---|---|
| **Product Manager** | Đánh giá nhanh, có bằng chứng về một bản phát hành; trả lời các câu hỏi mở "nên cải thiện gì?" kèm hành động ưu tiên. |
| **Growth / Marketing** | So sánh đối thủ, theo dõi thứ hạng và cảm xúc review của app mình so với đối thủ. |
| **C-level / lãnh đạo** | Một kết luận nhanh, trung thực về một giả thuyết ("feature X có làm tăng doanh thu không?") trước khi ra quyết định. |
| **Bất kỳ ai theo dõi một app** | Tự đăng ký qua Telegram: **cảnh báo** khi app tụt rating/hạng hoặc đổi phiên bản, hoặc **báo cáo định kỳ** vào giờ đã chọn. |

Tất cả đều có thể dùng **mà không cần đội phân tích** — chỉ cần hỏi bằng ngôn ngữ tự nhiên.

---

## 3. Giải pháp & Giá trị (Solution & Value)

Veridex là một agent dạng module chạy trên **GreenNode AgentBase**. Bạn gửi cho nó một câu hỏi bằng
ngôn ngữ tự nhiên (hoặc một action tường minh); một **bộ định tuyến (router)** dùng LLM chọn đúng phân
tích cần chạy và trích xuất tên app, store và khoảng thời gian; agent lấy dữ liệu store trực tiếp qua
các **connector có kiểm soát theo năng lực (capability-gated)**, tính các thống kê **xác định
(deterministic)**, và chỉ dùng LLM cho những phần thực sự cần hiểu ngôn ngữ (gom cụm chủ đề, lập kế
hoạch, viết diễn giải). Mọi báo cáo được kết xuất thành markdown dễ đọc.

### Những gì agent làm được hôm nay (đã hoàn thiện và chạy được)

| Năng lực | Trả lời câu hỏi gì |
|---|---|
| **Metadata & thứ hạng store** (`uc1_store_metadata`) | Thông tin listing hiện tại + thứ hạng bảng xếp hạng iOS — danh mục, giá, phiên bản, rating — và những gì đã thay đổi so với lần chụp (snapshot) gần nhất. |
| **Review & cảm xúc** (`uc2_reviews_sentiment`) | Trong một khoảng thời gian: số lượng review, phân bố sao, tỉ lệ ngôn ngữ, cảm xúc, xu hướng theo tuần, cụm chủ đề khen/chê. |
| **Lịch sử phiên bản** (`uc3_version_changelog`) | Dòng thời gian các phiên bản kèm ngày phát hành và ghi chú phát hành (release notes). |
| **Dashboard KPI / xu hướng** (`uc4_kpi_dashboard`) | Rating, thứ hạng, số lượng đánh giá và phiên bản theo thời gian từ snapshot đã lưu, kèm chênh lệch đầu→cuối. |
| **Kiểm tra sức khỏe bản phát hành** (`uc6_version_impact`) | So sánh rating, tốc độ review và tỉ lệ tiêu cực **trước vs sau** bản phát hành mới nhất → 🟢 ổn / 🔴 hồi quy / 🟡 chưa kết luận. |
| **So sánh cạnh tranh** (`uc7_competitive_comparison`) | Đối đầu trực tiếp với đối thủ cùng danh mục về thứ hạng, rating, số lượng đánh giá, giá, phiên bản và hoạt động phát hành gần đây. |
| **Khai thác điểm yếu đối thủ** (`uc8_competitor_weakness`) | Gom cụm các điểm đau từ review tiêu cực của đối thủ thành danh sách cơ hội được ưu tiên, kèm trích dẫn bằng chứng. |
| **Cảnh báo bất thường** (`uc9_trend_alert`) | Phát hiện tụt rating, tụt hạng và đổi phiên bản từ lịch sử snapshot, kèm mức độ nghiêm trọng. |
| **Hỏi đáp PM dạng mở** (`uc10_insight_qa`) | Tự lập kế hoạch và chạy các phân tích phù hợp, rồi tổng hợp câu trả lời có trích dẫn kèm hành động ưu tiên. |
| **Kiểm tra giả thuyết** (`hypothesis_check`) | Đa lượt: kiểm tra một nhận định nhân quả ("rating giảm *do* bản cập nhật") và trả về kết luận có kiểm soát (gated), dựa trên bằng chứng. |
| **Đăng ký theo dõi qua Telegram** (`manage_subscription`) | Người dùng tự đăng ký (panel 🔔 trên UI) nhận thông báo về Telegram của mình theo 2 chế độ — **Cảnh báo bất thường** (chỉ báo khi tụt rating/hạng hoặc đổi phiên bản; kiểm tự động hằng ngày) hoặc **Báo cáo định kỳ** (gửi tình hình app vào giờ đã chọn). Bộ lập lịch nội bộ tự chạy, không cần cron ngoài. |

### Giá trị

- **Vài phút, không phải vài giờ** — việc đọc review thủ công trước đây giờ chỉ là một câu hỏi.
- **Bằng chứng thay vì cảm tính** — con số được tính một cách xác định từ dữ liệu store thật, không phải
  do LLM đoán.
- **Trung thực về mặt phân tích** — Hypothesis Checker có một *cổng kiểm soát (gate)*: nếu dữ liệu cần để
  chứng minh một nhận định không lấy được (ví dụ doanh thu mà không có nguồn trả phí), kết luận bị giới
  hạn ở mức "chưa kết luận" thay vì bịa ra sự tự tin. Ước lượng được dán nhãn là ước lượng; tương quan
  không bị bán thành nhân quả.
- **Song ngữ** — tự nhận diện tiếng Việt vs tiếng Anh và trả lời tương ứng.
- **Không bao giờ làm sập runtime** — connector suy giảm mượt mà (thiếu một nguồn → báo cáo chỉ-có-chỉ-số,
  không bao giờ trả lỗi 500).

### Cảnh báo & đăng ký theo dõi (qua Telegram)

Bất kỳ ai cũng tự đăng ký theo dõi một app/game ngay trong giao diện chat (panel **🔔 Cảnh báo**) — chỉ cần `chat_id` Telegram của mình; **bot token là bí mật phía server**, người dùng không bao giờ chạm tới. Mỗi đăng ký chọn 1 trong 2 chế độ:

- **🔔 Cảnh báo bất thường** — chỉ nhắn khi UC9 phát hiện biến động (tụt rating/hạng, đổi phiên bản). Được kiểm **tự động hằng ngày** — không cần chọn giờ.
- **📊 Báo cáo định kỳ** — luôn gửi tình hình app (rating/hạng/phiên bản hiện tại + biến động nếu có) vào **giờ bạn chọn** (hằng ngày hoặc hằng tuần).

Một **bộ lập lịch nội bộ chạy sẵn trong runtime** (bật mặc định, `ENABLE_SCHEDULER=0` để tắt) thực thi việc này — **không cần cron ngoài**. Telegram tự chặn gửi tới chat chưa `/start` bot nên không spam được người lạ; có nút **"Gửi thử"** để xác nhận kênh. Chưa cấu hình `TELEGRAM_BOT_TOKEN` thì chạy **dry-run** an toàn (ghi log, không gửi). *Lưu ý:* runtime AgentBase dùng đĩa ephemeral nên đăng ký reset sau mỗi lần redeploy.

---

## 4. Mô hình & LLM — Khai báo MaaS

> **Agent này CHỈ dùng GreenNode MaaS. KHÔNG sử dụng bất kỳ nhà cung cấp mô hình bên ngoài nào (OpenAI, Anthropic, v.v.).**

- Toàn bộ suy luận LLM đi qua **GreenNode MaaS** thông qua endpoint **tương thích OpenAI**
  (`langchain_openai.ChatOpenAI`), cấu hình bằng `LLM_BASE_URL` + `LLM_API_KEY` được cấp phát qua skill
  `/agentbase-llm`. Thư viện client tương thích OpenAI, **nhưng host và thông tin xác thực trỏ tới
  GreenNode MaaS, không trỏ tới API của OpenAI.**
- **Các mô hình dùng:** mô hình trong danh mục GreenNode MaaS — ví dụ `google/gemma-4-31b-it` (nhanh,
  khuyến nghị làm mặc định) và các biến thể Qwen. Hãy chọn một mô hình instruction-tuned nhanh cho
  `LLM_MODEL`.
- Không có khóa (key) cho, hay lời gọi tới, bất kỳ nhà cung cấp mô hình nào ngoài MaaS ở bất cứ đâu trong
  dự án này.

Phụ thuộc ngoài *không-phải-mô-hình* duy nhất (tùy chọn) là **Sensor Tower** (`SENSORTOWER_AUTH_TOKEN`),
một nguồn *dữ liệu* cho chỉ số iOS cao cấp — **không phải LLM**. Nó là tùy chọn; agent chạy đầy đủ trên
các nguồn miễn phí mà không cần token này.

---

## 5. Cách chạy (How to run)

### Yêu cầu trước
- Python **3.10+** (image Docker dùng 3.12)
- Thông tin GreenNode MaaS cho LLM (`LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`) — cấp phát bằng
  `/agentbase-llm`

### Chạy cục bộ

```bash
# 1. Môi trường
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Cấu hình — copy file mẫu và điền LLM_* (token Sensor Tower là tùy chọn)
cp .env.example .env

# 3. Khởi động — phục vụ tại http://0.0.0.0:8080
python main.py
```

Server cung cấp ba endpoint:
- `GET /health` — kiểm tra sẵn sàng (**không** gọi LLM)
- `GET /` — giao diện chat web tích hợp (mở bằng trình duyệt)
- `POST /invocations` — entrypoint của agent

### Gọi qua API

Ngôn ngữ tự nhiên (router dùng LLM tự chọn action và trích params):
```bash
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" \
  -d '{"message": "kiểm tra sức khỏe bản cập nhật Android mới nhất của Instagram"}'
```

Action tường minh (xác định, không qua router):
```bash
curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" -d '{
  "action": "uc6_version_impact",
  "params": {"app": "Spotify", "store": "ios", "country": "us"}
}'
```

Kiểm tra health:
```bash
curl http://127.0.0.1:8080/health
```

### Kiểm thử (Tests)

```bash
# Bộ test offline + lint (không cần mạng/LLM) — đúng những gì CI chạy:
pip install -r requirements-dev.txt
ruff check .          # pyflakes
pytest                # unit test mock, xác định (tests/test_*.py)

# Script smoke chạy thật (gọi store/LLM thật; không được pytest thu thập):
./venv/bin/python tests/test_uc6_version_impact.py            # tổng hợp + iTunes & Google Play thật
./venv/bin/python tests/test_uc6_version_impact.py --no-live  # chỉ assert offline
./venv/bin/python tests/verify_uc1_store_metadata.py          # metadata UC1 (live)
./venv/bin/python tests/verify_uc2_reviews_sentiment.py       # review & sentiment UC2 (live)
```

### Triển khai (GreenNode AgentBase)

Dùng các skill AgentBase (repo cùng cấp `greennode-agentbase-skills`):
`/agentbase-llm` (cấp khóa MaaS) → `/agentbase-deploy` (build → push → runtime) →
`/agentbase-monitor` (logs/metrics). Trên production, lưu `SENSORTOWER_AUTH_TOKEN` qua
`/agentbase-identity`, không để trong `.env`.

---

## 6. Có thể tùy chỉnh ở đâu (What to customize)

Veridex được thiết kế để hầu hết mở rộng chỉ là **thả thêm một file** — không có danh sách trung tâm nào
cần sửa, vì `core/registry.py` tự động phát hiện bất cứ thứ gì bạn thêm vào.

### Mở rộng agent (thả một file)
| Để thêm… | Làm thế này |
|---|---|
| **Một phân tích mới** | File mới trong `usecases/` kế thừa `UseCase` (đặt `name`, `description`, `input_schema`; cài đặt `run`). Tự đăng ký và định tuyến được. |
| **Một nguồn dữ liệu mới** | File mới trong `connectors/` kế thừa `AppDataConnector` (đặt `name`, `stores`, `capabilities()`). Thêm vào `PREFERENCE` trong `core/deps.py` để được ưu tiên cho một capability. |
| **Một framework phân tích mới** | File mới trong `frameworks/` kế thừa `Framework` (dùng bởi Hypothesis Checker). |
| **Một kênh đầu ra mới** | File mới trong `outputs/` kế thừa `OutputChannel`. |

### Điều chỉnh hành vi (cấu hình trong `.env`)
| Biến | Tác dụng |
|---|---|
| `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | Dùng mô hình + endpoint GreenNode MaaS nào (**bắt buộc**). |
| `LLM_TIMEOUT` / `LLM_MAX_RETRIES` | Chờ MaaS chậm bao lâu trước khi suy giảm (mặc định 60s / 0). |
| `HYPOTHESIS_ENSEMBLE_MODELS` | Danh sách mô hình MaaS (ngăn cách bằng dấu phẩy) để biểu quyết đa số kết luận giả thuyết (bỏ trống = một mô hình). |
| `SENSORTOWER_AUTH_TOKEN` | Dữ liệu iOS cao cấp (tùy chọn); ngày token có quyền truy cập reviews, phân tích review iOS bật lên mà không cần sửa code. |
| `DEFAULT_STORE` / `DEFAULT_COUNTRY` | Giá trị mặc định khi người dùng không chỉ định. |
| `SNAPSHOT_DIR` / `CONVERSATION_DIR` / `SUBSCRIPTION_DIR` | Nơi lưu lịch sử — trỏ vào **volume bền vững (persistent)** để sống sót qua các lần redeploy. |
| `ENABLE_SCHEDULER` / `SCHEDULER_INTERVAL_SECONDS` | Bộ lập lịch watch nội bộ **chạy mặc định** (poll mỗi 300s); đặt `ENABLE_SCHEDULER=0` để tắt (vd nhiều replica + cron ngoài). |
| `ALERT_TZ` / `ALERT_DEFAULT_HOUR` | Múi giờ tính lịch (mặc định `Asia/Ho_Chi_Minh`) + giờ kiểm hằng ngày cho đăng ký chế độ "cảnh báo" (mặc định 9). |
| `ALERT_MAX_SUBS` / `ALERT_MAX_SUBS_PER_CHAT` | Giới hạn số đăng ký (mặc định 200 toàn hệ thống / 20 mỗi chat). |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Gửi Telegram — token là bí mật server; `chat_id` mỗi user khai trong UI. Không có token = dry-run an toàn (chỉ ghi log). |
| `WATCHLIST_FILE` / `ALERT_WATCHLIST` | Watchlist toàn cục (operator) cho chu kỳ cảnh báo (ví dụ `"Zalo\|both\|vi, com.spotify.music\|android"`). |

### Điều chỉnh logic phân tích
- **Ngưỡng kết luận (verdict thresholds)** cho kiểm tra sức khỏe bản phát hành là các hằng số module ở
  đầu file `usecases/uc6_version_impact.py`.
- **Thứ tự ưu tiên nguồn** theo từng capability (connector nào được thử trước) nằm trong `PREFERENCE`
  tại `core/deps.py`.

---

## Kiến trúc (tham quan 1 phút)

```
main.py            # Entrypoint AgentBase: cổng 8080 · GET /health · GET / (chat UI) · POST /invocations
core/              # llm · router (LLM-first) · registry (tự phát hiện) · deps (capability→connector)
connectors/        # itunes · appstore_reviews · ios_charts · googleplay · sensortower
usecases/          # uc1..uc10 · hypothesis_check · manage_subscription · help
frameworks/        # các engine phân rã nhận định cho Hypothesis Checker
outputs/           # bộ kết xuất markdown
storage/           # snapshot chỉ số hằng ngày · subscriptions
scheduler/         # chu kỳ watch của UC9 + cảnh báo Telegram
ui/                # chat web tích hợp (chat.html)
```

`main.py` là file duy nhất import SDK nền tảng; mọi thứ còn lại là Python thuần, kiểm thử đơn vị được.
Use case không bao giờ gọi tên một nguồn dữ liệu cụ thể — nó yêu cầu một **capability** (`reviews`,
`metadata`, `ranking`, …) và các connector được thử theo thứ tự nguồn-tốt-nhất-trước với cơ chế dự
phòng (fallback) mượt mà.

### Nguồn dữ liệu (thực tế 2026)
| Nguồn | Chi phí | Cung cấp |
|---|---|---|
| **iTunes Search/Lookup** | miễn phí | Tìm kiếm + metadata iOS (rating, phiên bản, ngày phát hành) |
| **App Store reviews** (RSS + catalog API) | miễn phí | Review iOS kèm ngày |
| **iOS charts** (Marketing-Tools RSS) | miễn phí | Thứ hạng iOS top-free/paid (tối đa 100) |
| **Google Play** (`google-play-scraper`) | miễn phí | Metadata Android **và** review kèm ngày |
| **Sensor Tower** | tùy chọn (cần khóa) | Review/lượt tải/doanh thu/thứ hạng iOS cao cấp — *tùy phạm vi của token* |

Toàn bộ dữ liệu là **công khai / ẩn danh** theo rulebook cuộc thi — không có PII của khách hàng.

> **Chi tiết hơn:** `CLAUDE.md` (kiến trúc & quy ước đầy đủ) và `docs/specs/` (tài liệu thiết kế).
