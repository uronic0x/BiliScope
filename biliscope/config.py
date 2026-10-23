from __future__ import annotations
from dataclasses import asdict, dataclass, fields
import json
from urllib.parse import urlparse
from .runtime import RUNTIME, inside, atomic_json

@dataclass
class Settings:
    language: str = 'cn'
    answer_language: str = 'cn'
    base_url: str = 'https://api.deepseek.com'
    model: str = 'deepseek-flash'
    vision: bool = True
    initial_frames: int = 4
    extra_frames: int = 4
    max_minutes: int = 30
    max_download_mb: int = 256
    asr: bool = True
    remember_key: bool = False
    prompt_preset: str = 'strict'
    system_prompt: str = ''
    injection_guard: bool = True
    include_comments: bool = False
    function_tools: bool = True
    instruction_role: str = 'system'
    token_limit_parameter: str = 'max_tokens'
    max_output_tokens: int = 6000
    api_timeout_seconds: int = 180
    require_api_key: bool = True
    request_extra_json: str = '{}'

    def validate(self):
        for name in ('vision','asr','remember_key','injection_guard','include_comments','function_tools','require_api_key'):
            if type(getattr(self,name)) is not bool:raise ValueError('API_OPTIONS')
        if self.language not in ('cn','en') or self.answer_language not in ('cn','en'):
            raise ValueError('LANGUAGE')
        u = urlparse(self.base_url)
        if u.username or u.password or u.query or u.fragment or not u.hostname:
            raise ValueError('API_URL')
        if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('127.0.0.1','localhost','::1')):
            raise ValueError('API_HTTPS')
        if not self.model.strip() or len(self.model) > 160:
            raise ValueError('MODEL')
        for key, low, high in [('initial_frames',0,8),('extra_frames',0,8),
                               ('max_minutes',1,120),('max_download_mb',16,1024)]:
            if not low <= int(getattr(self,key)) <= high:
                raise ValueError(key)
        from .prompts import PRESETS
        if self.prompt_preset not in PRESETS or not isinstance(self.system_prompt,str) or len(self.system_prompt)>20000:
            raise ValueError('PROMPT_PRESET')
        if self.instruction_role not in ('system','developer') or self.token_limit_parameter not in ('max_tokens','max_completion_tokens','omit'):
            raise ValueError('API_OPTIONS')
        if not 64<=int(self.max_output_tokens)<=64000 or not 10<=int(self.api_timeout_seconds)<=600:
            raise ValueError('API_OPTIONS')
        from .llm_options import extra_parameters
        extra_parameters(self.request_extra_json)
        return self

    @classmethod
    def load(cls):
        p = inside(RUNTIME/'config'/'settings.json')
        if not p.exists():
            return cls()
        d = json.loads(p.read_text(encoding='utf-8'))
        return cls(**{f.name:d[f.name] for f in fields(cls) if f.name in d}).validate()

    def save(self):
        self.validate()
        atomic_json(RUNTIME/'config'/'settings.json', asdict(self))
