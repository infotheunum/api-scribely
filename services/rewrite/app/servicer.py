from __future__ import annotations

import grpc
from scribely.rewrite.v1 import rewrite_pb2_grpc

_NOT_IMPLEMENTED_MSG = (
    "{} is not implemented yet — scribely-rewrite business logic lands in Phase 4 (ТЗ §6.6)"
)


class RewriteServicer(rewrite_pb2_grpc.RewriteServiceServicer):
    """Phase 0 skeleton: every RPC in the ТЗ §6.6 contract exists on the
    wire from the first commit, but returns UNIMPLEMENTED until Phase 4
    fills in Enrichment/Rewrite/SEO/Tags/Image/Keywords/Feedback/
    PromptVersion logic."""

    def _unimplemented(self, context: grpc.ServicerContext, method: str) -> None:
        context.abort(grpc.StatusCode.UNIMPLEMENTED, _NOT_IMPLEMENTED_MSG.format(method))

    def EnrichCluster(self, request, context):
        self._unimplemented(context, "EnrichCluster")

    def ResearchKeywords(self, request, context):
        self._unimplemented(context, "ResearchKeywords")

    def RewriteCluster(self, request, context):
        self._unimplemented(context, "RewriteCluster")

    def SuggestTags(self, request, context):
        self._unimplemented(context, "SuggestTags")

    def GenerateSeoPack(self, request, context):
        self._unimplemented(context, "GenerateSeoPack")

    def SuggestImageBrief(self, request, context):
        self._unimplemented(context, "SuggestImageBrief")

    def RegenerateDraft(self, request, context):
        self._unimplemented(context, "RegenerateDraft")

    def SubmitEditFeedback(self, request, context):
        self._unimplemented(context, "SubmitEditFeedback")

    def GetRewriterStyle(self, request, context):
        self._unimplemented(context, "GetRewriterStyle")

    def UpsertRewriterStyle(self, request, context):
        self._unimplemented(context, "UpsertRewriterStyle")

    def GetPromptVersion(self, request, context):
        self._unimplemented(context, "GetPromptVersion")
