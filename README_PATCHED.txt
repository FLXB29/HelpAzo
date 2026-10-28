Bản vá v1.0.24 - Nâng cấp tích hợp Mistral AI (Pixtral Vision)

1. TÍNH NĂNG MỚI:
- Hỗ trợ gọi trực tiếp API của Mistral AI (https://docs.mistral.ai/models) qua endpoint chính thức:
  https://api.mistral.ai/v1/chat/completions
- Sử dụng các model Multimodal / Vision tiên tiến nhất của Mistral:
  + "pixtral-large-latest" (124B): Model thị giác & suy luận mạnh nhất của Mistral, đọc ảnh đề thi cực chuẩn.
  + "pixtral-12b-2409" (12B): Model thị giác nhanh, nhẹ và tiết kiệm chi phí.
  + "mistral-small-latest": Model nhỏ hỗ trợ xử lý đa phương tiện.
  + "pixtral-large-2411": Ghim phiên bản Pixtral Large.
- Cơ chế tự động fallback thông minh: nếu model chính bị quá tải / rate-limit / lỗi 404/429, tool sẽ tự động chuyển sang model dự phòng trong fallback_models.
- Chuẩn hoá payload hình ảnh gửi theo chuẩn Mistral Data URI (data:image/png;base64,...).
- Hỗ trợ định dạng JSON Object từ AI (response_format: {"type": "json_object"}).

2. CÁCH CẤU HÌNH API KEY CHO MISTRAL:
Bạn có thể thiết lập Mistral API Key theo 1 trong các cách sau:
- Cách 1 (Khuyên dùng): Dán API key vào file mykey\mistral_key.txt
- Cách 2: Điền vào config\settings.json -> api.mistral_key: "..."
- Cách 3: Đặt biến môi trường hệ thống: MISTRAL_API_KEY
* Lưu ý: Tool vẫn tương thích ngược nếu bạn dùng OpenRouter key (sk-or-v1-...).

3. CÁCH SỬ DỤNG:
- Chạy bằng file thực thi: Chạy trực tiếp cap_solve_v1.0.24.exe
- Chạy bằng file batch: Chạy run.bat
- Chạy bằng mã nguồn Python: python main.py
- Đóng gói lại thành file exe khi sửa code: Chạy build_exe.bat

4. PHÍM TẮT:
- Ctrl + Shift + X: Chụp màn hình và giải đề trắc nghiệm
- Nút cuộn chuột giữa (Middle Mouse Click): Chụp & giải nhanh
- Tab: Phím dự phòng để chụp & giải
- Space: Đóng cửa sổ hiển thị kết quả
- Ctrl + Shift + L: Buộc dừng khẩn cấp và dọn sạch tiến trình
- Esc: Thoát chương trình
