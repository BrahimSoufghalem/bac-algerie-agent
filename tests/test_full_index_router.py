import json

import httpx
import pytest
from pydantic import ValidationError

from bac.agent.engine import AgentEngine
from bac.agent.full_index import (
    FullIndexCoordinator, build_catalog, parse_route, prune_contained, verifier_body,
)
from bac.agent.models import ModelConfig
from bac.agent.provider import ModelError
from bac.agent.presets import presets, validate_preset
from bac.agent.tools import Tools
from bac.core.db import js, uid
from tests.grounding_fixture import publish_reference
from tests.test_agent import chat_and_config

CFG = {"provider":"google","protocol":"google",
       "base_url":"https://generativelanguage.googleapis.com/v1beta","model":"gemini-3.5-flash-lite",
       "selector_enabled":True,"temperature":0,"max_tokens":1000}


def test_document_scope_must_be_active_and_published(services,monkeypatch):
    from fastapi.testclient import TestClient
    from bac.api.main import create_app
    from bac.core.auth import create_user
    async def valid_url(*args):
        return None
    monkeypatch.setattr("bac.api.main.validate_base_url",valid_url)
    create_user(services.db,"owner-index@example.com","Strong-password-123","Owner",role="owner")
    client=TestClient(create_app(services))
    login=client.post("/api/auth/login",json={
        "email":"owner-index@example.com","password":"Strong-password-123"})
    cfg=CFG | {"selector_document_id":"missing-document"}
    reply=client.put("/api/owner/models/selector",json={"config":cfg,"api_key":"PRIVATE-TEST-KEY"},
                     headers={"X-CSRF-Token":login.json()["csrf"]})
    assert reply.status_code==422
    assert "PRIVATE-TEST-KEY" not in reply.text
    assert not services.db.rows("SELECT * FROM active_selector")


def response(name, args):
    return httpx.Response(200,json={
        "candidates":[{"finishReason":"STOP","content":{"parts":[{"functionCall":{"name":name,"args":args}}]}}],
        "usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":20},
    })


def selector(services):
    id_=uid("full_index_cfg")
    services.db.execute("INSERT INTO context_selectors VALUES(?,?,?,?)",
                        (id_,js(CFG),services.vault.encrypt("PRIVATE-KEY"),1))
    services.db.execute("INSERT OR REPLACE INTO active_selector VALUES(1,?)",(id_,))
    return services.db.one("SELECT * FROM context_selectors WHERE id=?",(id_,))


@pytest.mark.parametrize("args",[
    {"status":[],"goals":[],"question":""},
    {"status":"read","goals":[],"question":""},
    {"status":"read","goals":[{"goal":"x","ids":["unknown"]}],"question":""},
    {"status":"clarify","goals":[],"question":""},
    {"status":"clarify","goals":[],"question":"See https://private.invalid"},
    {"status":"clarify","goals":[],"question":"Choose S1?"},
    {"status":"read","goals":[{"goal":"x","ids":["S1","S2","S3","S4"]}],"question":""},
])
def test_reject_invalid_contract(args):
    with pytest.raises(ModelError):
        parse_route(args,{"S1","S2","S3","S4"})


def test_complementary_parts_and_shared_source_are_allowed():
    plan={"status":"read","goals":[{"goal":"exercise and solution","ids":["S1","S2"]}],"question":""}
    assert parse_route(plan,{"S1","S2"})["selected_ids"]==["S1","S2"]
    plan["goals"]=[{"goal":"a","ids":["S1"]},{"goal":"b","ids":["S1"]}]
    assert parse_route(plan,{"S1"})["selected_ids"]==["S1"]
    with pytest.raises(ModelError):
        parse_route({"status":"read","ids":["S2"],"question":""},{"S1"},verify=True)


def test_unused_question_field_is_never_rendered_or_used():
    out=parse_route({"status":"read","ids":["S1"],"question":"Task label echoed by provider"},
                    {"S1"},verify=True)
    assert out["question"]=="" and out["selected_ids"]==["S1"]
    out=parse_route({"status":"no_new","goals":[],"question":"Ignored task label"},{"S1"})
    assert out["question"]==""


def test_no_read_decisions_discard_known_alternative_ids():
    out=parse_route({"status":"clarify","goals":[{"goal":"time","ids":["S1","S2"]}],
                     "question":"Which kind of time?"},{"S1","S2"})
    assert out["status"]=="clarify" and out["goals"]==[] and out["selected_ids"]==[]
    out=parse_route({"status":"no_new","ids":["S1"],"question":"Ignored task label"},
                    {"S1"},verify=True)
    assert out["ids"]==[] and out["question"]=="" and out["selected_ids"]==[]
    with pytest.raises(ModelError):
        parse_route({"status":"clarify","goals":[{"goal":"x","ids":["unknown"]}],
                     "question":"Which?"},{"S1"})


def test_pruning_only_containment_in_same_version_file():
    rows={
        "S1":{"version_id":"v","metadata":{"file_id":"a"},"start_order":1,"end_order":100},
        "S2":{"version_id":"v","metadata":{"file_id":"a"},"start_order":20,"end_order":30},
        "S3":{"version_id":"v","metadata":{"file_id":"b"},"start_order":20,"end_order":30},
        "S4":{"version_id":"v","metadata":{"file_id":"a"},"start_order":101,"end_order":120},
    }
    assert prune_contained(["S1","S2","S3","S4"],rows)==["S1","S3","S4"]
    assert prune_contained(["S2","S4"],rows)==["S2","S4"]


def test_private_comments_assets_removed_without_losing_math():
    text="<!-- source PRIVATE-ID -->\n# title\n$x=v t$\n![x](/api/library/assets/PRIVATE-ID)\nActual prose."
    clean=verifier_body(text)
    assert "PRIVATE-ID" not in clean and "/api/" not in clean
    assert "$x=v t$" in clean and "Actual prose" in clean


def test_only_llm_configuration_remains():
    fields=ModelConfig.model_fields
    assert not {"selector_strategy","selector_min_confidence","selector_min_margin"} & fields.keys()
    with pytest.raises(ValidationError):
        ModelConfig(base_url="https://example.org/v1",model="x",
                    protocol="evaluation")
    for key,value in [("selector_strategy","candidates"),("selector_min_confidence",0.55),
                      ("selector_min_margin",0.1)]:
        with pytest.raises(ValidationError):
            ModelConfig(base_url="https://example.org/v1",model="x",**{key:value})
    for preset in presets("selector"):
        assert preset["protocol"] in {"openai","google"}
        assert "laya" not in preset["model"].lower()
    assert any(p["protocol"]=="anthropic" for p in presets("agent"))
    with pytest.raises(ValueError):
        validate_preset(ModelConfig(provider="custom",base_url="https://example.org",
                                    model="x",protocol="anthropic"),"selector")


@pytest.mark.asyncio
async def test_first_route_then_actual_read_then_verification_then_remember(services):
    node=await publish_reference(services)
    user,chat=chat_and_config(services)
    row=selector(services)
    index,mapping=build_catalog(services)
    alias=next(a for a,n in mapping.items() if n["id"]==node)
    calls=[]
    def handler(req):
        body=json.loads(req.content);name=body["tools"][0]["functionDeclarations"][0]["name"]
        data=json.loads(body["contents"][0]["parts"][0]["text"])
        assert node not in js(body) and user["id"] not in js(body)
        assert not services.db.rows("SELECT * FROM loaded_context")
        calls.append(name)
        if name=="route_sections":
            assert data["complete_book_index"]==index and "Neglect air resistance" not in js(body)
            return response(name,{"status":"read","goals":[{"goal":"projectile","ids":[alias]}],"question":""})
        assert "Neglect air resistance" in js(body)
        return response(name,{"status":"read","ids":[alias],"question":""})
    services.selector_transport=httpx.MockTransport(handler)
    rid=AgentEngine(services).enqueue(chat,user,"اشرح القذف")
    run=services.db.one("SELECT * FROM agent_runs WHERE id=?",(rid,))
    result=await FullIndexCoordinator(services,row).prepare(run,Tools(services,user,chat,rid),"اشرح القذف")
    assert result["node"]["id"]==node
    assert calls==["route_sections"]
    assert len(services.db.rows("SELECT * FROM loaded_context"))==1
    assert {r["feature"] for r in services.db.rows("SELECT * FROM model_usage")}=={
        "source_selection"}


@pytest.mark.asyncio
@pytest.mark.parametrize("with_alternative_ids",[False,True])
async def test_clarification_finishes_without_teacher_call(services,with_alternative_ids):
    await publish_reference(services)
    user,chat=chat_and_config(services);selector(services)
    question="تقصد أي نوع من الحركة؟"
    _,mapping=build_catalog(services)
    goals=[{"goal":"ambiguous movement","ids":[next(iter(mapping))]}] if with_alternative_ids else []
    services.selector_transport=httpx.MockTransport(lambda req:response(
        "route_sections",{"status":"clarify","goals":goals,"question":question}))
    class NeverTeacher:
        async def decision_stream(self, messages, tools):
            from tests.test_context_decisions import call
            yield {"type":"result","message":call("assess_context",{"decision":"uncertain","source_ids":[]})}
        async def stream(self,*args):
            raise AssertionError("Teacher must not run on clarification")
            yield
    services.chat_factory=lambda cfg,key:NeverTeacher()
    engine=AgentEngine(services);rid=engine.enqueue(chat,user,"اشرح الحركة")
    await engine.process(engine.claim())
    assert services.db.one("SELECT status FROM agent_runs WHERE id=?",(rid,))["status"]=="COMPLETED"
    answer=services.db.one("SELECT content,sources FROM messages WHERE role='assistant'")
    assert answer["content"]==question and json.loads(answer["sources"])==[]
    assert not services.db.rows("SELECT * FROM loaded_context")
    assert len(services.db.rows("SELECT * FROM model_usage"))==2


def test_retired_stored_router_never_enqueues_or_decrypts_key(services):
    from fastapi import HTTPException
    user,chat=chat_and_config(services)
    row=selector(services)
    legacy=CFG | {"protocol":"evaluation","selector_strategy":"candidates"}
    services.db.execute("UPDATE context_selectors SET config=? WHERE id=?",(js(legacy),row["id"]))
    row=services.db.one("SELECT * FROM context_selectors WHERE id=?",(row["id"],))
    with pytest.raises(ModelError,match="ROUTER_RECONFIGURATION_REQUIRED"):
        FullIndexCoordinator(services,row)
    with pytest.raises(HTTPException) as err:
        AgentEngine(services).enqueue(chat,user,"اشرح القذف")
    assert err.value.status_code==409
    assert not services.db.rows("SELECT * FROM agent_runs")
    assert not services.db.rows("SELECT * FROM messages")
    assert not services.db.rows("SELECT * FROM model_usage")


def owner_client(services):
    from fastapi.testclient import TestClient
    from bac.api.main import create_app
    from bac.core.auth import create_user
    create_user(services.db,"router-owner@example.com","Strong-password-123","Owner",role="owner")
    client=TestClient(create_app(services))
    login=client.post("/api/auth/login",json={
        "email":"router-owner@example.com","password":"Strong-password-123"})
    return client,{"X-CSRF-Token":login.json()["csrf"]}


def test_retired_router_requires_explicit_new_setup_without_network(services,monkeypatch):
    async def valid_url(*args):return None
    monkeypatch.setattr("bac.api.main.validate_base_url",valid_url)
    row=selector(services)
    legacy=CFG | {"provider":"custom","protocol":"evaluation",
                  "base_url":"https://old-provider.invalid/v1","model":"retired-model",
                  "selector_strategy":"candidates","selector_min_confidence":0.55,
                  "selector_min_margin":0.1}
    services.db.execute("UPDATE context_selectors SET config=? WHERE id=?",(js(legacy),row["id"]))
    client,headers=owner_client(services)
    def never(req):
        raise AssertionError("Retired router must not make network requests")
    services.connection_transport=httpx.MockTransport(never)
    saved=client.get("/api/owner/models").json()["items"][0]
    assert saved["router_requires_reconfiguration"] and not saved["key_saved"]
    assert saved["protocol"]=="google" and saved["selector_enabled"] is False
    assert not {"selector_strategy","selector_min_confidence","selector_min_margin"} & saved.keys()
    assert "PRIVATE-KEY" not in js(saved) and "retired-model" not in js(saved)
    assert client.post("/api/owner/models/selector/test",
                       json={"confirm":True},headers=headers).status_code==409
    cfg={k:v for k,v in saved.items() if k in ModelConfig.model_fields}
    assert client.put("/api/owner/models/selector",json={
        "config":cfg},headers=headers).status_code==422
    actual=services.db.one("SELECT * FROM context_selectors WHERE id=?",(row["id"],))
    assert json.loads(actual["config"])==legacy and actual["encrypted_key"]==row["encrypted_key"]


def test_compatible_stored_llm_keeps_key_and_drops_obsolete_public_fields(services,monkeypatch):
    async def valid_url(*args):return None
    monkeypatch.setattr("bac.api.main.validate_base_url",valid_url)
    row=selector(services)
    original=CFG | {"selector_strategy":"candidates","selector_min_confidence":0.55,
                    "selector_min_margin":0.1}
    services.db.execute("UPDATE context_selectors SET config=? WHERE id=?",(js(original),row["id"]))
    client,headers=owner_client(services)
    saved=client.get("/api/owner/models").json()["items"][0]
    assert saved["key_saved"] and not saved["router_requires_reconfiguration"]
    cfg={k:v for k,v in saved.items() if k in ModelConfig.model_fields}
    response=client.put("/api/owner/models/selector",json={"config":cfg},headers=headers)
    assert response.status_code==200
    new=services.db.one("SELECT * FROM context_selectors WHERE id=?",(response.json()["id"],))
    assert new["encrypted_key"]==row["encrypted_key"]
    assert not {"selector_strategy","selector_min_confidence","selector_min_margin"} & json.loads(new["config"]).keys()
    assert json.loads(services.db.one("SELECT config FROM context_selectors WHERE id=?",(row["id"],))["config"])==original