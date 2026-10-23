import json
from .domain import AppError

RESERVED={'model','messages','tools','tool_choice','parallel_tool_calls','stream','n',
          'functions','function_call','max_tokens','max_completion_tokens'}

def extra_parameters(raw):
    try:
        if not isinstance(raw,str) or len(raw)>16000:raise ValueError()
        result=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        if not isinstance(result,dict) or RESERVED.intersection(result):raise ValueError()
        return result
    except (ValueError,TypeError):raise AppError('API_EXTRA_OPTIONS') from None
