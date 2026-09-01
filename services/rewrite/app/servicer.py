from __future__ import annotations

import logging

import grpc
from rewrite_app.db import new_session
from rewrite_app.enrich.enrichment import enrich_cluster
from rewrite_app.prompt.versions import get_active_prompt_version
from rewrite_app.rewrite.orchestrator import rewrite_cluster
from common.integration_reasons import format_integration_error
from rewrite_app.rewrite.rotation import AllKeysExhaustedError
from rewrite_app.settings import RewriteSettings
from scribely.rewrite.v1 import rewrite_pb2, rewrite_pb2_grpc

logger = logging.getLogger(__name__)

_NOT_IMPLEMENTED_MSG = (
    "{} is not implemented yet — scribely-rewrite business logic lands in Phase 4 (ТЗ §6.6)"
)


def _sources_text(sources) -> str:
    lines = []
    for s in sources:
        outlet = s.source_name or "(издание не указано — не атрибутируй по названию)"
        lines.append(
            f"[{s.title}] ({outlet}, {s.language}, tier {s.tier}, {s.url})\n"
            f"{s.excerpt_or_full_text}"
        )
    return "\n\n".join(lines)


def _facts_text(facts) -> str:
    if not facts:
        return "(нет)"
    return "\n".join(f"- [{f.kind}] {f.text}" for f in facts)


def _flags_text(ctx) -> str:
    return (
        f"press_release={ctx.press_release}, regulated={ctx.regulated}, "
        f"market_sensitive={ctx.market_sensitive}, fact_conflict={ctx.fact_conflict}"
        + (f" ({ctx.fact_conflict_note})" if ctx.fact_conflict_note else "")
    )


class RewriteServicer(rewrite_pb2_grpc.RewriteServiceServicer):
    """ТЗ §6.6. EnrichCluster/RewriteCluster/GetPromptVersion — real (Фаза
    4). SuggestTags/GenerateSeoPack/SuggestImageBrief standalone variants
    stay UNIMPLEMENTED — RewriteCluster already returns them inline in
    the same call (economizes free-tier LLM spend, ТЗ §4.4); the
    standalone versions exist for RegenerateDraft-style partial re-runs,
    not built in this phase. ResearchKeywords/GetRewriterStyle/
    SubmitEditFeedback are contract-only mocks (theunum.io vector store
    and keyword providers are explicitly post-MVP, ТЗ §4.14/§4.18)."""

    def _unimplemented(self, context: grpc.ServicerContext, method: str) -> None:
        context.abort(grpc.StatusCode.UNIMPLEMENTED, _NOT_IMPLEMENTED_MSG.format(method))

    def EnrichCluster(self, request, context):
        settings = RewriteSettings()
        db = new_session()
        try:
            sources_text = _sources_text(request.sources)
            try:
                result, key_alias, model = enrich_cluster(db, settings, sources_text=sources_text)
            except AllKeysExhaustedError as exc:
                context.abort(
                    grpc.StatusCode.UNAVAILABLE,
                    format_integration_error(
                        exc.code,
                        f"all OpenRouter keys exhausted: {exc}",
                    ),
                )
            except RuntimeError as exc:
                # Dead-letter (ТЗ §4.20): logged with full context instead of
                # a persisted quarantine table (which Phase 8's reporting
                # will need) — cluster stays unenriched, worker's queue
                # naturally retries it next tick since it never got marked done.
                logger.error(
                    "EnrichCluster dead-letter for cluster %s: %s", request.cluster_id, exc
                )
                context.abort(grpc.StatusCode.INTERNAL, str(exc))

            response = rewrite_pb2.EnrichClusterResponse(
                context=rewrite_pb2.ClusterContext(
                    cluster_id=request.cluster_id,
                    sources=request.sources,
                    facts=[
                        rewrite_pb2.ExtractedFact(kind=f.kind, text=f.text) for f in result.facts
                    ],
                    press_release=result.press_release,
                    regulated=result.regulated,
                    market_sensitive=result.market_sensitive,
                    fact_conflict=result.fact_conflict,
                    fact_conflict_note=result.fact_conflict_note,
                    trace_id=request.trace_id,
                )
            )
            logger.info(
                "EnrichCluster cluster=%s key=%s model=%s facts=%d",
                request.cluster_id,
                key_alias,
                model,
                len(result.facts),
            )
            return response
        finally:
            db.close()

    def RewriteCluster(self, request, context):
        settings = RewriteSettings()
        db = new_session()
        try:
            prompt_version = get_active_prompt_version(db)
            sources_text = _sources_text(request.context.sources)
            facts_text = _facts_text(request.context.facts)
            flags_text = _flags_text(request.context)
            style_note = (
                f"Оверлей стиля рерайтера {request.style_overlay.assignee_user_id} "
                f"(contract/mock в MVP, ТЗ §4.14) — используй house style."
                if request.style_overlay.assignee_user_id
                else "Оверлей стиля не назначен — используй house style."
            )

            try:
                result, key_alias, model = rewrite_cluster(
                    db,
                    settings,
                    prompt_version,
                    sources_text=sources_text,
                    facts_text=facts_text,
                    flags_text=flags_text,
                    style_overlay_note=style_note,
                )
            except AllKeysExhaustedError as exc:
                context.abort(
                    grpc.StatusCode.UNAVAILABLE,
                    format_integration_error(
                        exc.code,
                        f"all OpenRouter keys exhausted: {exc}",
                    ),
                )
            except RuntimeError as exc:
                logger.error(
                    "RewriteCluster dead-letter for cluster %s: %s",
                    request.context.cluster_id,
                    exc,
                )
                context.abort(grpc.StatusCode.INTERNAL, str(exc))

            attribution_urls = [s.url for s in request.context.sources]
            draft = rewrite_pb2.DraftContent(
                title_en=result.title_en,
                body_en=result.body_en,
                title_ru=result.title_ru,
                body_ru=result.body_ru,
                title_en_variants=result.title_en_variants,
                title_ru_variants=result.title_ru_variants,
                attribution_urls=attribution_urls,
                sponsor_flag=result.sponsor_flag,
                press_release_flag=result.press_release_flag,
                disclaimer_flag=result.disclaimer_flag,
                fact_conflict=request.context.fact_conflict,
                suggested_category_slug=result.suggested_category_slug,
                tags=[rewrite_pb2.TagCandidate(slug=t.slug, name=t.name) for t in result.tags],
                seo_en=rewrite_pb2.SeoPack(**result.seo_en.model_dump()),
                seo_ru=rewrite_pb2.SeoPack(**result.seo_ru.model_dump()),
                image_brief=rewrite_pb2.ImageBrief(**result.image_brief.model_dump()),
            )
            logger.info(
                "RewriteCluster cluster=%s key=%s model=%s prompt_version=%s",
                request.context.cluster_id,
                key_alias,
                model,
                prompt_version.id,
            )
            return rewrite_pb2.RewriteClusterResponse(
                draft=draft,
                prompt_version_id=str(prompt_version.id),
                rewrite_usage=rewrite_pb2.LlmUsage(key_alias=key_alias, model=model, attempt=1),
                translate_usage=rewrite_pb2.LlmUsage(key_alias=key_alias, model=model, attempt=1),
            )
        finally:
            db.close()

    def GetPromptVersion(self, request, context):
        db = new_session()
        try:
            version = get_active_prompt_version(db)
            return rewrite_pb2.GetPromptVersionResponse(
                version=rewrite_pb2.PromptVersion(
                    id=str(version.id),
                    status=version.status,
                    notes=version.notes or "",
                    approved_by=str(version.approved_by) if version.approved_by else "",
                )
            )
        finally:
            db.close()

    def ResearchKeywords(self, request, context):
        # Wordstat/DataForSEO adapter is post-MVP (ТЗ §4.18) — mock
        # returns no insights so callers degrade to keyword-less SEO
        # rather than erroring.
        return rewrite_pb2.ResearchKeywordsResponse(insights=[])

    def SuggestTags(self, request, context):
        self._unimplemented(context, "SuggestTags")

    def GenerateSeoPack(self, request, context):
        self._unimplemented(context, "GenerateSeoPack")

    def SuggestImageBrief(self, request, context):
        self._unimplemented(context, "SuggestImageBrief")

    def RegenerateDraft(self, request, context):
        self._unimplemented(context, "RegenerateDraft")

    def SubmitEditFeedback(self, request, context):
        # theunum.io style-vector proxy is post-MVP (ТЗ §4.14) — mock
        # acknowledges receipt without upserting anything.
        return rewrite_pb2.SubmitEditFeedbackResponse(accepted=True)

    def GetRewriterStyle(self, request, context):
        return rewrite_pb2.GetRewriterStyleResponse(
            profile=rewrite_pb2.RewriterStyleProfile(user_id=request.user_id, available=False)
        )

    def UpsertRewriterStyle(self, request, context):
        # Same theunum.io proxy as SubmitEditFeedback — contract/mock in MVP.
        return rewrite_pb2.UpsertRewriterStyleResponse(accepted=True)
