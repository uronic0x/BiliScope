"""Deterministic publication gates; heuristics supplement, never prove, safety."""
from __future__ import annotations
import re
import unicodedata
from .domain import AppError
from .runtime import redact

PATTERNS=[
 ('instruction_override',r'(?i)(ignore|disregard|override)\s+(all\s+)?(previous|prior|above|system|developer)\s+(instructions?|prompts?|rules?)'),
 ('instruction_override_cn',r'(忽略|无视|覆盖|抛弃).{0,12}(之前|此前|以上|系统|开发者).{0,10}(指令|提示词|规则)'),
 ('forged_role',r'(?i)(\[/?(?:system|developer)\]|<\|(?:im_start|system|developer)[^>]*>|(?:system|developer)\s*message\s*:)'),
 ('secret_request',r'(?i)(send|reveal|print|exfiltrate|upload).{0,50}(api.?key|cookie|secret|system prompt|password)'),
 ('secret_request_cn',r'(发送|上传|泄露|打印|输出).{0,25}(密钥|密码|Cookie|系统提示词|API.?Key)'),
 ('encoded_instruction',r'(?i)(decode|execute|run).{0,20}(base64|powershell|shell command|javascript)'),
]


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',str(text)) if unicodedata.category(c)!='Cf')


def findings(text):
    value=normalized(text)
    return [label for label,pattern in PATTERNS if re.search(pattern,value)]


def evidence_findings(ev,*,include_comments=True):
    chunks=[ev.title,ev.description]+[x.get('content','') for x in ev.transcript]
    if include_comments:chunks += [x.get('message','') for x in ev.comments]
    return sorted({label for chunk in chunks for label in findings(chunk)})


def safe_auto_comment(text,*,strict=True,max_chars=300):
    if not isinstance(text,str):raise AppError('AUTO_OUTPUT_BLOCKED','not_text')
    value=normalized(text).strip()
    if not value or len(value)>max_chars:raise AppError('AUTO_OUTPUT_BLOCKED','length')
    if value.startswith(('{','[','```','<')):
        raise AppError('AUTO_OUTPUT_BLOCKED','structured_or_code_output')
    # Only the frozen owner UID may be mentioned; model-generated destinations
    # cannot be used, even if a local custom prompt asks for them.
    if '@' in value:raise AppError('AUTO_OUTPUT_BLOCKED','model_mention')
    if re.search(r'(?i)(https?://|www\.|data:|javascript:|file:|(?:[a-z0-9-]+\.)+(?:com|net|org|cn|io)\b)',value):
        raise AppError('AUTO_OUTPUT_BLOCKED','external_link')
    if re.search(r'(?i)(\bsk-[a-z0-9_-]{8,}|Bearer\s+\S+|SESSDATA\s*[=:]|bili_jct\s*[=:])',value):
        raise AppError('AUTO_OUTPUT_BLOCKED','credential_pattern')
    if value!=redact(value):raise AppError('AUTO_OUTPUT_BLOCKED','known_secret')
    if any(unicodedata.category(c)=='Cc' and c not in '\n\t' for c in value):
        raise AppError('AUTO_OUTPUT_BLOCKED','control_character')
    if strict and findings(value):raise AppError('AUTO_OUTPUT_BLOCKED','injection_pattern')
    return value
