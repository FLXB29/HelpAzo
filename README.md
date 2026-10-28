# HelpAzo

Công cụ hỗ trợ chụp màn hình và phân tích câu hỏi trắc nghiệm qua Vision LLM (Mistral AI / GLM).

## Tính năng
- Chụp nhanh màn hình qua phím tắt (mặc định: `Ctrl+Shift+X` hoặc click chuột giữa).
- Phân tích và trích xuất đáp án bằng AI (`zai-glm-5-3-flash`, `mistral-large-4`).
- Hiển thị bảng đáp án gọn gàng dạng popup trong suốt trên màn hình.
- Phím tắt thoát: `Ctrl+Shift+Q` (hoặc `Ctrl+Shift+L` để thoát khẩn cấp).

## Cấu hình
1. Thêm API key của bạn vào file `mykey/mistral_key.txt` hoặc cấu hình trong `config/settings.json`.
2. Chạy ứng dụng bằng `run.bat` hoặc `python main.py`.
