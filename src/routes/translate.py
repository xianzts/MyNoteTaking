import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Blueprint, current_app, jsonify, request
from openai import OpenAI

translate_bp = Blueprint('translate', __name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / 'prompts' / 'translate_prompt.md'
SUPPORTED_LANGUAGES = {'Chinese', 'English', 'Japanese', 'Korean', 'French', 'Spanish'}
MODEL = 'nvidia/nemotron-3-ultra-550b-a55b:free'
FALLBACK_MODEL = 'deepseek/deepseek-chat'
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 1


def _parse_translation_response(response_content):
    if not isinstance(response_content, str) or not response_content.strip():
        raise ValueError('The model returned an empty response')

    response_content = response_content.strip()
    fenced_json = re.fullmatch(
        r'```(?:json)?\s*(.*?)\s*```',
        response_content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_json:
        response_content = fenced_json.group(1).strip()

    translated_result = json.loads(response_content)
    if not isinstance(translated_result, dict):
        raise ValueError('The translation response must be a JSON object')

    translated_title = translated_result.get('translated_title')
    translated_content = translated_result.get('translated_content')
    if not isinstance(translated_title, str) or not isinstance(translated_content, str):
        raise ValueError('The translation response is missing translated fields')

    return {
        'translated_title': translated_title,
        'translated_content': translated_content,
    }


def _translate_with_retries(client, model, messages):
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                extra_body={'reasoning': {'enabled': True}},
            )
            return _parse_translation_response(response.choices[0].message.content)
        except Exception as error:
            current_app.logger.warning(
                'Translation attempt %d/%d failed for model %s (%s): %s',
                attempt + 1,
                MAX_RETRIES + 1,
                model,
                type(error).__name__,
                error,
            )
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_DELAY_SECONDS)


def _describe_error(error):
    detail = ' '.join(str(error).split()) or 'No additional details'
    return f'{type(error).__name__}: {detail[:200]}'


@translate_bp.route('/translate', methods=['POST'])
def translate_text():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'A JSON request body is required'}), 400

    title = data.get('title', '')
    content = data.get('content', '')
    target_language = data.get('target_language')
    if not isinstance(title, str) or not isinstance(content, str):
        return jsonify({'error': 'Title and content must be strings'}), 400
    if not title.strip() and not content.strip():
        return jsonify({'error': 'Title or content is required'}), 400
    if not isinstance(target_language, str) or target_language not in SUPPORTED_LANGUAGES:
        return jsonify({'error': 'Unsupported target language'}), 400

    load_dotenv(ROOT_DIR / '.env')
    api_key = os.getenv('OPEN_ROUTER_KEY')
    if not api_key:
        return jsonify({'error': 'OPEN_ROUTER_KEY is not configured'}), 503

    try:
        prompt_template = PROMPT_PATH.read_text(encoding='utf-8')
        system_prompt = prompt_template.format(target_language=target_language)
        user_prompt = json.dumps(
            {'title': title, 'content': content},
            ensure_ascii=False,
        )
        client = OpenAI(
            base_url='https://openrouter.ai/api/v1',
            api_key=api_key,
        )
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]
    except Exception as error:
        current_app.logger.exception('Failed to prepare translation request')
        return jsonify({
            'error': f'翻译请求准备失败（{_describe_error(error)}），请稍后重试。',
        }), 502

    model_errors = []
    for model in (MODEL, FALLBACK_MODEL):
        try:
            translated_result = _translate_with_retries(client, model, messages)
            return jsonify({**translated_result, 'target_language': target_language})
        except Exception as error:
            model_errors.append(error)
            current_app.logger.error(
                'Translation failed for model %s after %d attempts: %s',
                model,
                MAX_RETRIES + 1,
                _describe_error(error),
            )

    error_message = (
        '翻译服务暂时不可用，主模型和备用模型均已重试失败。'
        f'主模型错误：{_describe_error(model_errors[0])}；'
        f'备用模型错误：{_describe_error(model_errors[1])}。请稍后重试。'
    )
    return jsonify({'error': error_message}), 502