from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from .views import (
    ApiProjectViewSet, ApiCollectionViewSet, ApiRequestViewSet,
    EnvironmentViewSet, RequestHistoryViewSet, TestSuiteViewSet,
    TestSuiteRequestViewSet, TestExecutionViewSet, UserViewSet,
    ScheduledTaskViewSet, TaskExecutionLogViewSet, NotificationLogViewSet,
    TaskNotificationSettingViewSet, OperationLogViewSet,
    ApiDashboardViewSet, AIServiceConfigViewSet
)
from .yapi_views import YApiConnectionViewSet
from .param_views import analyze_api_params, get_analysis, save_analysis, list_analyses
from .clarify_views import generate_clarify_questions, get_clarification, save_clarification
from .case_views import generate_cases, list_cases, update_case, delete_case, batch_confirm_cases, execute_cases, case_report, analyze_execution
from .prompt_config_views import prompt_configs, update_prompt_config, delete_prompt_config, get_default_prompt
from .agent_views import plan_scenario, run_scenario

router = DefaultRouter()
router.register(r'dashboard', ApiDashboardViewSet, basename='dashboard')
router.register(r'projects', ApiProjectViewSet)
router.register(r'collections', ApiCollectionViewSet)
router.register(r'requests', ApiRequestViewSet)
router.register(r'environments', EnvironmentViewSet)
router.register(r'histories', RequestHistoryViewSet)
router.register(r'test-suites', TestSuiteViewSet)
router.register(r'test-suite-requests', TestSuiteRequestViewSet)
router.register(r'test-executions', TestExecutionViewSet)
router.register(r'users', UserViewSet)
router.register(r'scheduled-tasks', ScheduledTaskViewSet, basename='scheduledtask')
router.register(r'task-execution-logs', TaskExecutionLogViewSet, basename='taskexecutionlog')
router.register(r'notification-logs', NotificationLogViewSet)
router.register(r'task-notification-settings', TaskNotificationSettingViewSet)
router.register(r'operation-logs', OperationLogViewSet)
router.register(r'ai-service-configs', AIServiceConfigViewSet, basename='aiserviceconfig')
router.register(r'yapi-connections', YApiConnectionViewSet, basename='yapiconnection')

urlpatterns = [
    path('api-testing/', include(router.urls)),
    # 参数分析
    path('api-testing/param-analysis/batch/', analyze_api_params),
    path('api-testing/param-analysis/', list_analyses),
    path('api-testing/param-analysis/<int:request_id>/save/', save_analysis),
    path('api-testing/param-analysis/<int:request_id>/', get_analysis),
    # 澄清确认
    path('api-testing/clarify/<int:request_id>/generate/', generate_clarify_questions),
    path('api-testing/clarify/<int:request_id>/', get_clarification),
    path('api-testing/clarify/<int:request_id>/save/', save_clarification),
    # 测试用例
    path('api-testing/cases/generate/', generate_cases),
    path('api-testing/cases/', list_cases),
    path('api-testing/cases/<int:case_id>/', update_case),
    path('api-testing/cases/<int:case_id>/delete/', delete_case),
    path('api-testing/cases/batch-confirm/', batch_confirm_cases),
    path('api-testing/cases/execute/', execute_cases),
    path('api-testing/cases/report/', case_report),
    path('api-testing/cases/analyze/', analyze_execution),
    # Agent 接口自动化
    path('api-testing/agent/plan/', plan_scenario),
    path('api-testing/agent/run/', run_scenario),
    # 接口测试提示词配置
    path('api-testing/prompt-configs/default/', get_default_prompt),
    path('api-testing/prompt-configs/', prompt_configs),
    path('api-testing/prompt-configs/<int:config_id>/', update_prompt_config),
    path('api-testing/prompt-configs/<int:config_id>/delete/', delete_prompt_config),
]

# 添加媒体文件路由
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
