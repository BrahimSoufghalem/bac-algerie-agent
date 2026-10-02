"""Record provider-reported quantities, never estimate missing tokens/cache as zero."""

import time
from fastapi import HTTPException
from bac.agent.provider import ModelError


def record(
    s,
    cfg,
    usage,
    duration,
    *,
    user,
    config_id,
    run=None,
    feature="teaching",
    status="ok",
    target=None,
):
    def number(v):
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None

    inp = number(usage.get("prompt_tokens"))
    out = number(usage.get("completion_tokens"))
    details = usage.get("prompt_tokens_details") or {}
    cached = number(details.get("cached_tokens")) if isinstance(details, dict) else None
    if cached is not None and inp is not None and cached > inp:
        cached = None
    cost = None
    if (
        inp is not None
        and out is not None
        and cfg.get("input_price_per_million") is not None
        and cfg.get("output_price_per_million") is not None
    ):
        # Unknown cache reporting/pricing: normal input price yields a labelled upper-price estimate, not an invoice.
        cost = (
            inp * cfg["input_price_per_million"] + out * cfg["output_price_per_million"]
        ) / 1e6
        if cached is not None and cfg.get("cached_price_per_million") is not None:
            cost += (
                cached
                * (cfg["cached_price_per_million"] - cfg["input_price_per_million"])
                / 1e6
            )
    s.db.execute(
        "INSERT INTO model_usage(run_id,user_id,config_id,model,input_tokens,output_tokens,cached_tokens,estimated_cost,duration_ms,created_at,feature,status,target) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run,
            user,
            config_id,
            cfg["model"],
            inp,
            out,
            cached,
            cost,
            duration,
            time.time(),
            feature,
            status,
            target,
        ),
    )


def check_budget(s, user):
    u = s.db.one("SELECT * FROM users WHERE id=?", (user,))
    if not u or not u["active"]:
        raise ModelError("ACCOUNT_DISABLED")
    if u["daily_tokens"] is not None:
        r = s.db.one(
            "SELECT sum(coalesce(input_tokens,0)+coalesce(output_tokens,0)) n,sum(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL THEN 1 ELSE 0 END) missing FROM model_usage WHERE user_id=? AND created_at>?",
            (user, time.time() - 86400),
        )
        if r["missing"]:
            raise ModelError("TOKEN_BUDGET_USAGE_UNKNOWN")
        if (r["n"] or 0) >= u["daily_tokens"]:
            raise ModelError("TOKEN_ALLOWANCE_REACHED")


def report(s, user=None, days=30):
    if not 1 <= days <= 365:
        raise HTTPException(422, "Period must be 1–365 days")
    sql = "created_at>?"
    args = [time.time() - days * 86400]
    if user:
        sql += " AND user_id=?"
        args.append(user["id"])
    items = s.db.rows(
        "SELECT model,feature,count(*) calls,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,sum(cached_tokens) cached_tokens,sum(estimated_cost) estimated_cost,avg(duration_ms) latency_ms,sum(status!='ok') errors,sum(input_tokens IS NULL OR output_tokens IS NULL) missing_usage,sum(cached_tokens IS NULL) missing_cache,sum(estimated_cost IS NULL) missing_cost FROM model_usage WHERE "
        + sql
        + " GROUP BY model,feature",
        args,
    )
    out = {
        "items": items,
        "days": days,
        "cost_is_estimate": True,
        "currency": "owner-configured pricing unit",
        "missing_usage_calls": sum(r["missing_usage"] for r in items),
        "pricing_note": "Missing cache priced at ordinary input rate; estimates are not provider invoices. Missing prices/usage are unavailable, not zero.",
    }
    where = "created_at>?" + (" AND user_id=?" if user else "")
    out["runs"] = s.db.one(
        "SELECT count(*) total,sum(status IN ('FAILED','INTERRUPTED')) errors FROM agent_runs WHERE "
        + where,
        args,
    )
    if user:
        u = s.db.one("SELECT * FROM users WHERE id=?", (user["id"],))
        out["limits"] = {
            k: u[k]
            for k in (
                "daily_limit",
                "daily_tokens",
                "messages_per_minute",
                "max_active_runs",
                "budget_alert",
            )
        }
        daily = s.db.one(
            "SELECT sum(estimated_cost) cost,sum(estimated_cost IS NULL) missing FROM model_usage WHERE user_id=? AND created_at>?",
            (user["id"], time.time() - 86400),
        )
        out["budget_alert_reached"] = (
            u["budget_alert"] is not None and (daily["cost"] or 0) >= u["budget_alert"]
        )
        out["budget_unknown"] = bool(daily["missing"])
    return out


class MeteredVision:
    def __init__(self, s, provider, cfg):
        self.s, self.provider, self.cfg = s, provider, cfg

    async def extract(self, image, page, width, height):
        started = time.monotonic()
        usage = {}
        status = "error"
        try:
            doc, usage = await self.provider.extract(image, page, width, height)
            status = "ok"
            return doc, usage
        finally:
            config = self.cfg.get("_platform_config_id")
            actor = self.cfg.get("_platform_actor_id")
            if config and actor:
                record(
                    self.s,
                    self.cfg,
                    usage,
                    (time.monotonic() - started) * 1000,
                    user=actor,
                    config_id=config,
                    feature="extraction",
                    status=status,
                    target=f"{image.parent.parent.name}:{page}",
                )
