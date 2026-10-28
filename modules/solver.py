import base64
from datetime import datetime
import json
import os
import re
import struct
import traceback
from typing import Any, Dict, List, Optional, Tuple
import zlib
from PIL import Image
import requests

from modules.path_utils import get_base_dir, resolve_runtime_path, resolve_settings_path

BASE_DIR = get_base_dir()
CONFIG_PATH = resolve_settings_path()
PROMPT_PATH = resolve_runtime_path('systemp_prompt.txt')
_LOG_FILE = os.path.join(BASE_DIR, 'debug_cap.log')

_DEFAULT_PROMPTS = {
    'english_exam': (
        "Bạn là AI chuyên giải đề thi Tiếng Anh trắc nghiệm (TOEIC, ngữ pháp, từ vựng, đọc hiểu). "
        "Nhiệm vụ: phân tích ảnh chụp đề, chọn đáp án đúng nhất cho từng câu.\n"
        "Chỉ trả về JSON thuần theo cấu trúc:\n"
        '{"results": [{"number": "1", "answer": "A", "details": "giải thích ngắn"}]}'
    ),
    'general_law': (
        "Bạn là trợ lý hỗ trợ pháp luật đại cương. Đọc kỹ ảnh câu hỏi trắc nghiệm, "
        "xác định nội dung pháp lý và chọn đáp án đúng nhất.\n"
        "Chỉ trả về JSON thuần theo cấu trúc:\n"
        '{"results": [{"number": "1", "answer": "A", "details": "giải thích ngắn"}]}'
    ),
    'generic_mcq': (
        "Bạn là trợ lý giải đề trắc nghiệm. Đọc kỹ ảnh câu hỏi trắc nghiệm, suy luận cẩn thận và chọn đáp án đúng nhất.\n"
        "Chỉ trả về JSON thuần theo cấu trúc:\n"
        '{"results": [{"number": "1", "answer": "A", "details": "giải thích ngắn"}]}'
    )
}

_DEFAULT_CONFIG = {
    "api": {
        "provider": "mistral",
        "mistral_key": "",
        "openrouter_key": "",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "model_id": "mistral-large-4",
        "timeout_seconds": 120,
        "fallback_models": [
            "mistral-large-4-0",
            "mistral-large-latest",
            "pixtral-large-latest",
            "pixtral-12b-2409"
        ],
        "use_response_schema": True,
        "retry_without_schema": True,
        "auto_fallback_on_vision_error": True,
        "max_repair_attempts": 1,
        "extra_headers": {}
    },
    "prompt": {
        "mode": "general_law",
        "prompt_file": "",
        "profiles_dir": "prompts",
        "extra_instruction": ""
    }
}

def _log(msg: str):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')
    line = f"[{timestamp}] [solver] {msg}\n"
    try:
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass
    print(f"[solver] {msg}")

def load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception as e:
        _log(f"Lỗi khi đọc file cấu hình: {e}")
        return {}

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result

def _load_effective_config() -> Dict[str, Any]:
    user_cfg = load_config()
    return _deep_merge(_DEFAULT_CONFIG, user_cfg)

def _read_key_file(rel_path: str) -> Optional[str]:
    full_path = resolve_runtime_path(rel_path)
    if os.path.exists(full_path):
        try:
            with open(full_path, 'r', encoding='utf-8-sig') as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass
    return None

def resolve_api_credentials(config: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Trả về (provider, api_key, endpoint).
    Ưu tiên tìm Mistral API key trước, nếu không có sẽ kiểm tra OpenRouter.
    """
    api_cfg = config.get('api', {})
    provider = str(api_cfg.get('provider', 'mistral')).strip().lower()

    # 1. Tìm Mistral key
    mistral_key = (
        api_cfg.get('mistral_key')
        or api_cfg.get('api_key')
        or _read_key_file(os.path.join('mykey', 'mistral_key.txt'))
        or _read_key_file(os.path.join('mykey', 'api_key.txt'))
        or os.getenv('MISTRAL_API_KEY')
    )

    # 2. Tìm OpenRouter key
    openrouter_key = (
        api_cfg.get('openrouter_key')
        or _read_key_file(os.path.join('mykey', 'openrouter_key.txt'))
        or os.getenv('OPENROUTER_API_KEY')
    )

    # Kiểm tra key trong bất kỳ file .txt nào trong mykey/ nếu vẫn chưa thấy
    if not mistral_key and not openrouter_key:
        mykey_dir = resolve_runtime_path('mykey')
        if os.path.exists(mykey_dir) and os.path.isdir(mykey_dir):
            for fname in os.listdir(mykey_dir):
                if fname.lower().endswith('.txt'):
                    key_cand = _read_key_file(os.path.join('mykey', fname))
                    if key_cand:
                        if key_cand.startswith('sk-or-'):
                            openrouter_key = key_cand
                        else:
                            mistral_key = key_cand
                        break

    configured_endpoint = api_cfg.get('endpoint') or api_cfg.get('base_url')

    if provider == 'openrouter' or (not mistral_key and openrouter_key):
        resolved_provider = 'openrouter'
        api_key = (openrouter_key or mistral_key or '').strip()
        endpoint = configured_endpoint or "https://openrouter.ai/api/v1/chat/completions"
    else:
        resolved_provider = 'mistral'
        api_key = (mistral_key or openrouter_key or '').strip()
        endpoint = configured_endpoint or "https://api.mistral.ai/v1/chat/completions"

    return resolved_provider, api_key, endpoint

def load_system_prompt(config: Dict[str, Any]) -> str:
    prompt_cfg = config.get('prompt', {})
    mode = prompt_cfg.get('mode', 'general_law')
    prompt_file = prompt_cfg.get('prompt_file', '')
    profiles_dir = prompt_cfg.get('profiles_dir', 'prompts')
    extra_instruction = prompt_cfg.get('extra_instruction', '').strip()

    system_prompt = ""
    # Thử đọc từ prompt_file chỉ định rõ ràng
    if prompt_file:
        cand = resolve_runtime_path(prompt_file)
        if os.path.exists(cand):
            try:
                with open(cand, 'r', encoding='utf-8-sig') as f:
                    system_prompt = f.read().strip()
            except Exception:
                pass

    # Thử đọc từ profiles_dir / {mode}.txt
    if not system_prompt and mode:
        cand = resolve_runtime_path(profiles_dir, f"{mode}.txt")
        if os.path.exists(cand):
            try:
                with open(cand, 'r', encoding='utf-8-sig') as f:
                    system_prompt = f.read().strip()
            except Exception:
                pass

    # Thử đọc từ systemp_prompt.txt
    if not system_prompt and os.path.exists(PROMPT_PATH):
        try:
            with open(PROMPT_PATH, 'r', encoding='utf-8-sig') as f:
                system_prompt = f.read().strip()
        except Exception:
            pass

    # Fallback vào dict mặc định
    if not system_prompt:
        system_prompt = _DEFAULT_PROMPTS.get(mode, _DEFAULT_PROMPTS['generic_mcq'])

    if extra_instruction:
        system_prompt = f"{system_prompt}\n\n[HƯỚNG DẪN BỔ SUNG]:\n{extra_instruction}"

    return system_prompt

def encode_image(image_path: str) -> str:
    """Nén ảnh screenshot và mã hoá Base64 PNG."""
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            _log(f"encode_image: loaded {w}x{h} from {os.path.basename(image_path)}")
            # Chuyển sang RGB nếu là RGBA hoặc P
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='PNG', optimize=True)
            png_bytes = buffer.getvalue()
            b64_str = base64.b64encode(png_bytes).decode('utf-8')
            _log(f"encode_image: PNG {len(png_bytes)} bytes → base64 {len(b64_str)} chars")
            return b64_str
    except Exception as e:
        _log(f"encode_image fallback: {e}")
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

def _normalize_results(data: Any) -> Dict[str, Any]:
    if isinstance(data, list):
        data = {"results": data}
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be dict or list")

    results = data.get('results')
    if not isinstance(results, list):
        # Hỗ trợ các key tiếng Việt / thay thế như 'ket_qua', 'answers', 'data', 'items'
        for alt_key in ('ket_qua', 'answers', 'data', 'questions', 'items', 'dap_an'):
            if isinstance(data.get(alt_key), list):
                results = data[alt_key]
                break

    # Nếu model trả về dict dạng {"1": "A", "2": "B"} hoặc {"cau_1": {...}}
    if not isinstance(results, list):
        converted = []
        for k, v in data.items():
            if k in ('message', 'note', 'ghi_chu', 'status', 'type'):
                continue
            if isinstance(v, dict):
                converted.append({
                    "number": str(v.get('number') or v.get('cau') or k).strip(),
                    "answer": str(v.get('answer') or v.get('dap_an') or '').strip(),
                    "details": str(v.get('details') or v.get('cach_giai') or v.get('giai_thich') or '').strip()
                })
            elif isinstance(v, (str, int, float)):
                converted.append({
                    "number": str(k).strip(),
                    "answer": str(v).strip(),
                    "details": ""
                })
        if converted:
            results = converted

    normalized = []
    if isinstance(results, list):
        for idx, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                normalized.append({
                    "number": str(idx),
                    "answer": str(item).strip(),
                    "details": ""
                })
                continue

            raw_num = item.get('number') or item.get('cau') or item.get('stt') or item.get('id') or idx
            number = str(raw_num).strip()

            raw_ans = (
                item.get('answer')
                or item.get('dap_an')
                or item.get('choice')
                or item.get('ans')
                or ''
            )
            answer = str(raw_ans).strip()
            # Nếu là trắc nghiệm chuẩn ABCD có dấu câu
            if len(answer) > 1 and answer[0].upper() in 'ABCD' and answer[1] in '.: )/-':
                answer = answer[0].upper()

            details = str(
                item.get('details')
                or item.get('cach_giai')
                or item.get('giai_thich')
                or item.get('explanation')
                or item.get('ghi_chu')
                or item.get('de_bai')
                or ''
            ).strip()

            normalized.append({
                "number": number,
                "answer": answer,
                "details": details
            })

    # Nếu AI không tìm thấy câu hỏi hoặc trả về results: []
    if not normalized:
        fallback_msg = (
            data.get('message')
            or data.get('note')
            or data.get('ghi_chu')
            or "AI không tìm thấy câu hỏi hoặc phương án đáp án trong ảnh chụp."
        )
        return {
            "results": [
                {
                    "number": "Thông báo",
                    "answer": "Không có đáp án",
                    "details": str(fallback_msg).strip()
                }
            ]
        }

    return {"results": normalized}

def _extract_json_candidates(text: str):
    text = text.strip()
    yield text

    # Khối markdown ```json ... ```
    fenced = re.findall(r'```(?:json)?\s*(.*?)```', text, flags=re.IGNORECASE | re.DOTALL)
    for item in fenced:
        yield item.strip()

    # Tìm cặp { ... } hoặc [ ... ] lớn nhất
    for opener, closer in (('{', '}'), ('[', ']')):
        start_idx = text.find(opener)
        end_idx = text.rfind(closer)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            yield text[start_idx:end_idx + 1].strip()

def _repair_json_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    # Bỏ trailing commas: ,} -> } hoặc ,] -> ]
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    return cleaned

def parse_model_output(raw_text: str) -> Dict[str, Any]:
    errors = []
    for candidate in _extract_json_candidates(raw_text):
        if not candidate:
            continue
        # Thử parse trực tiếp
        try:
            data = json.loads(candidate)
            return _normalize_results(data)
        except Exception as e:
            errors.append(f"direct: {e}")

        # Thử sửa lỗi cú pháp phổ biến
        try:
            repaired = _repair_json_text(candidate)
            data = json.loads(repaired)
            return _normalize_results(data)
        except Exception as e:
            errors.append(f"repaired: {e}")

    raise ValueError(f"Không thể phân tích dữ liệu JSON từ AI: {'; '.join(errors[-2:])}")

def _build_payload(
    model_id: str,
    system_prompt: str,
    image_base64: str,
    use_schema: bool = True,
    provider: str = "mistral"
) -> Dict[str, Any]:
    """
    Xây dựng payload Chat Completions theo chuẩn Mistral / OpenAI tương thích.
    """
    user_instruction = (
        "Phân tích ảnh chụp câu hỏi đính kèm, giải từng câu (bao gồm cả câu hỏi trắc nghiệm A/B/C/D, bài toán, tự luận ngắn hoặc điền khuyết). "
        "Với câu hỏi trắc nghiệm: answer là chữ cái đáp án đúng (A, B, C, D). "
        "Với bài toán hoặc câu hỏi khác: answer là đáp số hoặc kết quả ngắn gọn. "
        "Trả về định dạng JSON object với khóa 'results': [{\"number\": \"1\", \"answer\": \"A hoặc đáp số\", \"details\": \"giải thích ngắn gọn\"}]. "
        "Không được bỏ qua câu hỏi nào. Chỉ trả về JSON thuần."
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": user_instruction
                },
                {
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{image_base64}"
                }
            ]
        }
    ]

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.1
    }

    # Mistral và OpenAI hỗ trợ response_format: {"type": "json_object"}
    if use_schema:
        payload["response_format"] = {"type": "json_object"}

    return payload

def _build_repair_payload(model_id: str, raw_content: str) -> Dict[str, Any]:
    repair_prompt = (
        "Bạn là công cụ chuyển đổi định dạng. Hãy trích xuất và định dạng lại nội dung sau thành JSON thuần "
        "theo đúng schema: {\"results\": [{\"number\": \"1\", \"answer\": \"A\", \"details\": \"...\"}]}. "
        "Chỉ trả JSON, không thêm bất kỳ văn bản nào khác."
    )
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": raw_content}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

def _request_api(
    endpoint: str,
    api_key: str,
    payload: Dict[str, Any],
    timeout_seconds: int = 120,
    proxy_url: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None
) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    if extra_headers:
        headers.update(extra_headers)

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    return requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=timeout_seconds,
        proxies=proxies
    )

def _extract_response_content(response: requests.Response) -> str:
    data = response.json()
    choices = data.get('choices', [])
    if choices and len(choices) > 0:
        message = choices[0].get('message', {})
        content = message.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Các model suy luận như mistral-large-4 trả về mảng gồm các block 'thinking' và 'text'.
            # Chỉ lấy các block văn bản kết quả 'text', loại bỏ suy nghĩ trung gian 'thinking'.
            text_parts = [
                p.get('text', '') for p in content
                if isinstance(p, dict) and p.get('type') == 'text'
            ]
            if text_parts:
                return "".join(text_parts)
            # Fallback nếu không có type=='text' (loại bỏ block 'thinking')
            return "".join([
                p.get('text', '') for p in content
                if isinstance(p, dict) and p.get('type') != 'thinking'
            ])
    return ""

def _needs_retry_without_schema(status_code: int, body: str) -> bool:
    if status_code in (400, 404, 422):
        lower = body.lower()
        tokens = ('response_format', 'json_object', 'json_schema', 'structured output', 'schema')
        return any(t in lower for t in tokens)
    return False

def _is_vision_incompatible(status_code: int, body: str) -> bool:
    if status_code in (400, 404, 422):
        lower = body.lower()
        return any(t in lower for t in ('image', 'multimodal', 'vision', 'support image input'))
    return False

def _is_model_unavailable(status_code: int, body: str) -> bool:
    if status_code in (400, 404):
        lower = body.lower()
        tokens = ('not found', 'model not found', 'invalid model', 'no endpoints found', 'not a valid model id')
        return any(t in lower for t in tokens)
    return False

def _is_quota_or_rate_limit(status_code: int, body: str) -> bool:
    if status_code in (402, 429):
        return True
    if status_code in (400, 401, 403):
        lower = body.lower()
        tokens = ('credit', 'quota', 'rate limit', 'ratelimit', 'limit exceeded', 'balance', 'payment required')
        return any(t in lower for t in tokens)
    return False

def _model_candidates(config: Dict[str, Any], primary_model: str) -> List[str]:
    api_cfg = config.get('api', {})
    out = []
    if primary_model:
        out.append(primary_model.strip())
    fallback_models = api_cfg.get('fallback_models', [])
    if isinstance(fallback_models, list):
        for item in fallback_models:
            s = str(item).strip()
            if s and s not in out:
                out.append(s)
    if not out:
        out = ["pixtral-large-latest", "pixtral-12b-2409"]
    return out

def _call_and_parse(
    endpoint: str,
    api_key: str,
    model_id: str,
    system_prompt: str,
    image_base64: str,
    timeout_seconds: int,
    proxy_url: Optional[str],
    extra_headers: Optional[Dict[str, str]],
    use_schema: bool,
    max_repair_attempts: int,
    provider: str
) -> Dict[str, Any]:
    payload = _build_payload(model_id, system_prompt, image_base64, use_schema=use_schema, provider=provider)
    response = _request_api(
        endpoint=endpoint,
        api_key=api_key,
        payload=payload,
        timeout_seconds=timeout_seconds,
        proxy_url=proxy_url,
        extra_headers=extra_headers
    )

    _log(f"PHAN HOI: status={response.status_code} | headers={dict(response.headers)}")
    if response.status_code >= 400:
        _log(f"NOI DUNG LOI: {response.text[:2000]}")
        response.raise_for_status()

    raw_content = _extract_response_content(response)
    _log(f"NOI DUNG AI ({len(raw_content)} chars): {raw_content[:500]}")
    try:
        return parse_model_output(raw_content)
    except Exception as e:
        _log(f"PARSE JSON LOI: {e}")
        if max_repair_attempts > 0:
            _log("Thử gọi AI để sửa JSON...")
            repair_payload = _build_repair_payload(model_id, raw_content)
            repair_resp = _request_api(
                endpoint=endpoint,
                api_key=api_key,
                payload=repair_payload,
                timeout_seconds=timeout_seconds,
                proxy_url=proxy_url,
                extra_headers=extra_headers
            )
            if repair_resp.status_code < 400:
                repaired_content = _extract_response_content(repair_resp)
                return parse_model_output(repaired_content)
        raise

def solve_with_llm(image_path: str, proxy_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Hàm chính chụp ảnh và gọi Mistral AI để giải đề thi trắc nghiệm.
    Tự động thử các fallback model nếu gặp lỗi hoặc rate limit.
    """
    config = _load_effective_config()
    api_cfg = config.get('api', {})

    provider, api_key, endpoint = resolve_api_credentials(config)

    if not api_key:
        msg = (
            "Thiếu API Key! Vui lòng lưu Mistral API Key vào file mykey/mistral_key.txt "
            "hoặc config/settings.json (mục api.mistral_key)."
        )
        _log(msg)
        return {"error": msg}

    primary_model = api_cfg.get('model_id', 'pixtral-large-latest')
    timeout_seconds = int(api_cfg.get('timeout_seconds', 120))
    extra_headers = api_cfg.get('extra_headers', {})
    use_schema_default = bool(api_cfg.get('use_response_schema', True))
    retry_without_schema = bool(api_cfg.get('retry_without_schema', True))
    auto_fallback = bool(api_cfg.get('auto_fallback_on_vision_error', True))
    max_repair_attempts = int(api_cfg.get('max_repair_attempts', 1))

    system_prompt = load_system_prompt(config)
    image_base64 = encode_image(image_path)

    candidates = _model_candidates(config, primary_model)
    last_error_msg = ""

    for candidate_model in candidates:
        schema_modes = [use_schema_default]
        if use_schema_default and retry_without_schema:
            schema_modes.append(False)

        for use_schema in schema_modes:
            try:
                _log(f"GUI YEU CAU [{provider.upper()}] | endpoint={endpoint} | model={candidate_model} | schema={use_schema}")
                result = _call_and_parse(
                    endpoint=endpoint,
                    api_key=api_key,
                    model_id=candidate_model,
                    system_prompt=system_prompt,
                    image_base64=image_base64,
                    timeout_seconds=timeout_seconds,
                    proxy_url=proxy_url,
                    extra_headers=extra_headers,
                    use_schema=use_schema,
                    max_repair_attempts=max_repair_attempts,
                    provider=provider
                )
                return result

            except requests.exceptions.Timeout:
                last_error_msg = f"Timeout ({timeout_seconds}s) khi gọi model {candidate_model}."
                _log(f"TIMEOUT: {last_error_msg}")
                break  # thử model tiếp theo

            except requests.exceptions.RequestException as e:
                resp = getattr(e, 'response', None)
                status_code = getattr(resp, 'status_code', 0) if resp is not None else 0
                body = getattr(resp, 'text', str(e)) if resp is not None else str(e)
                last_error_msg = f"HTTP {status_code}: {body[:200]}"
                _log(f"CONNECT LOI: {last_error_msg}")

                if use_schema and _needs_retry_without_schema(status_code, body):
                    _log("Model không hỗ trợ schema format, đang thử lại không dùng schema...")
                    continue  # sang mode không dùng schema

                if auto_fallback and (_is_vision_incompatible(status_code, body) or _is_model_unavailable(status_code, body) or _is_quota_or_rate_limit(status_code, body)):
                    _log(f"Model {candidate_model} gặp lỗi ({status_code}), chuyển sang fallback model tiếp theo...")
                    break  # chuyển sang model tiếp theo

                break

            except Exception as e:
                last_error_msg = f"Lỗi xử lý: {str(e)}"
                _log(f"LOI KHAC: {last_error_msg}\n{traceback.format_exc()}")
                break

    return {"error": last_error_msg or "Không nhận được phản hồi hợp lệ từ AI."}
