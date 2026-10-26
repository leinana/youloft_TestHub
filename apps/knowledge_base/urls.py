from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import KnowledgeNodeViewSet, KnowledgeChangeLogViewSet
from .collect_views import collect_link, recognize_link
from .extract_views import extract_knowledge, classify_link, extract_grouped, regenerate_summary
from .collection_views import (
    create_collection, get_collection, create_proposal,
    get_proposal, decide_proposal, apply_proposal_view, check_coverage_view,
)

router = DefaultRouter()
router.register(r'nodes', KnowledgeNodeViewSet, basename='knowledge-node')
router.register(r'change-logs', KnowledgeChangeLogViewSet, basename='knowledge-changelog')

urlpatterns = [
    path('', include(router.urls)),
    path('collect/', collect_link, name='collect-link'),
    path('recognize/', recognize_link, name='recognize-link'),
    path('extract/', extract_knowledge, name='extract-knowledge'),
    path('classify/', classify_link, name='classify-link'),
    path('extract-grouped/', extract_grouped, name='extract-grouped'),
    path('regenerate-summary/', regenerate_summary, name='regenerate-summary'),
    # 采集批次 → 知识提议 → 审核 → 应用（新流程）
    path('collections/', create_collection, name='create-collection'),
    path('collections/<int:collection_id>/', get_collection, name='get-collection'),
    path('collections/<int:collection_id>/proposal/', create_proposal, name='create-proposal'),
    path('proposals/<int:proposal_id>/', get_proposal, name='get-proposal'),
    path('proposals/<int:proposal_id>/decide/', decide_proposal, name='decide-proposal'),
    path('proposals/<int:proposal_id>/apply/', apply_proposal_view, name='apply-proposal'),
    # 用例生成前：检查知识库覆盖情况
    path('coverage/', check_coverage_view, name='check-coverage'),
]
