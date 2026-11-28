import json
from pathlib import Path

import pytest

from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_rules import RulePolicyRequired, call_capability

PACK=Path(__file__).resolve().parents[2]/'packs/it_ops/v0.1'
TOOLS=json.loads((PACK/'practice/tool_permissions.json').read_text(encoding='utf-8'))['tools']
EXPECTED={'config':'github.code.read','trace':'ops.traces.read',
          'checklist':'github.actions.logs.read','json':'github.actions.logs.read','completion':'github.actions.logs.read',
          'injection':'github.issues.read','scope':'github.issues.read','permission':'github.issues.read','dedup':'github.issues.read',
          'conditional':'db.errors.read'}


@pytest.mark.parametrize('prefix,capability',EXPECTED.items())
@pytest.mark.parametrize('index',[1,2,3])
def test_known_context_calls_resolve_one_function(prefix,capability,index):
    ctx=from_tools(TOOLS,None)
    span={'name':'read_workflow_context','tool_args':{'scenario_id':f'{prefix}-{index}'}}
    assert call_capability(span,ctx['confirmation'],ctx['tool_access'],True)==capability


@pytest.mark.parametrize('value',['json-4','json-1-extra','unknown-1',None])
def test_unknown_context_not_assigned_a_function(value):
    ctx=from_tools(TOOLS,None)
    span={'name':'read_workflow_context','tool_args':{'scenario_id':value}}
    with pytest.raises(RulePolicyRequired,match='call_capability_unknown'):
        call_capability(span,ctx['confirmation'],ctx['tool_access'],True)
