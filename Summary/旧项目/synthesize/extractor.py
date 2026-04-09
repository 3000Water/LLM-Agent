"""
阶段一：从单份个人总结中提取结构化工作要点。

主要职责：
  - 调用 LLM，输出 JSON（9个key，每个key对应 list[str]）
  - 自动重试（JSON解析失败或API异常）
  - 返回标准化结果，缺失的key补空列表
"""

import json
import time
import logging
from openai import OpenAI

from synthesize.config import SECTIONS, DEEPSEEK_MODEL, TEMPERATURE_EXTRACT, MAX_RETRIES
from synthesize.prompts import EXTRACT_SYSTEM, EXTRACT_USER

logger = logging.getLogger(__name__)

# 所有合法的 section key
VALID_KEYS = {s["key"] for s in SECTIONS}


def extract_from_summary(client: OpenAI, summary_text: str, source_name: str = "") -> dict:
    """
    从一份个人总结中，按9个维度提取工作要点。

    Args:
        client      : 已初始化的 OpenAI 客户端（指向 DeepSeek）
        summary_text: 个人总结的纯文本内容
        source_name : 来源文件名，仅用于日志

    Returns:
        dict: {section_key: [bullet_str, ...], ...}，保证包含全部9个key
    """
    prompt = EXTRACT_USER.substitute(summary=summary_text)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"  [提取] {source_name}  尝试 {attempt}/{MAX_RETRIES}")
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=TEMPERATURE_EXTRACT,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            return _normalize(data, source_name)

        except json.JSONDecodeError as e:
            logger.warning(f"  [提取] JSON解析失败（{source_name}，第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [提取] {source_name} 全部重试失败，返回空结果")
                return _empty_result()
            time.sleep(2 ** attempt)

        except Exception as e:
            logger.warning(f"  [提取] API异常（{source_name}，第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [提取] {source_name} 全部重试失败，返回空结果")
                return _empty_result()
            time.sleep(2 ** attempt)


def _normalize(raw: dict, source_name: str) -> dict:
    """
    标准化 LLM 返回的 JSON：
      - 保证所有9个key都存在
      - 每个value都是 list[str]
      - 过滤掉非法key
    """
    result = _empty_result()
    for key, value in raw.items():
        if key in VALID_KEYS:
            if isinstance(value, list):
                result[key] = [str(v).strip() for v in value if v]
            else:
                logger.warning(f"  [normalize] {source_name}: key={key} value不是列表，已忽略")
        else:
            logger.debug(f"  [normalize] {source_name}: 未知key '{key}'，已忽略")
    return result


def _empty_result() -> dict:
    return {s["key"]: [] for s in SECTIONS}
