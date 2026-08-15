"""MongoDB 连接与集合访问模块。"""

from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.config import settings


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    """获取业务 MongoDB 客户端单例。"""
    return MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)


def get_database() -> Database:
    """获取业务数据库对象。"""
    return get_mongo_client()[settings.mongodb_database]


@lru_cache(maxsize=1)
def _get_auth_client() -> MongoClient:
    """获取统一认证（AI4MS）MongoDB 客户端单例。"""
    return MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)


def _get_auth_database() -> Database:
    """获取统一认证（AI4MS）数据库对象。"""
    return _get_auth_client()[settings.auth_database]


@lru_cache(maxsize=1)
def get_data_asset_client() -> MongoClient:
    """获取只读材料数据资产 MongoDB 客户端。"""
    uri = settings.data_asset_mongodb_uri or settings.mongodb_uri
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def get_data_asset_database() -> Database:
    """获取只读材料数据资产数据库对象。"""
    return get_data_asset_client()[settings.data_asset_mongodb_database]


def get_users_collection() -> Collection:
    """获取统一认证（AI4MS）users 集合。"""
    return _get_auth_database()["users"]


def get_invite_codes_collection() -> Collection:
    """获取统一认证（AI4MS）invite_codes 集合。"""
    return _get_auth_database()["invite_codes"]


def get_poly_tasks_collection() -> Collection:
    """获取 poly_tasks 集合。"""
    return get_database()["poly_tasks"]


def get_computation_runs_collection() -> Collection:
    """获取 computation_runs 集合。"""
    return get_database()["computation_runs"]


def get_computation_artifacts_collection() -> Collection:
    """获取 computation_artifacts 集合。"""
    return get_database()["computation_artifacts"]


def get_optimization_campaigns_collection() -> Collection:
    """获取 optimization_campaigns 集合。"""
    return get_database()["optimization_campaigns"]


def get_optimization_candidates_collection() -> Collection:
    """获取 optimization_candidates 集合。"""
    return get_database()["optimization_candidates"]


def get_optimization_suggestions_collection() -> Collection:
    """获取 optimization_suggestions 集合。"""
    return get_database()["optimization_suggestions"]


def get_optimization_observations_collection() -> Collection:
    """获取 optimization_observations 集合。"""
    return get_database()["optimization_observations"]


def get_service_integrations_collection() -> Collection:
    """获取 service_integrations 集合。"""
    return get_database()["service_integrations"]


def get_llm_routing_configs_collection() -> Collection:
    """获取 llm_routing_configs 集合。"""
    return get_database()["llm_routing_configs"]


def get_audit_events_collection() -> Collection:
    """获取 audit_events 集合。"""
    return get_database()["audit_events"]


def get_research_problem_specs_collection() -> Collection:
    """获取 research_problem_specs 集合。"""
    return get_database()["research_problem_specs"]


def get_execution_decisions_collection() -> Collection:
    """获取 execution_decisions 集合。"""
    return get_database()["execution_decisions"]


def get_manual_algorithm_workflows_collection() -> Collection:
    """获取 manual_algorithm_workflows 集合。"""
    return get_database()["manual_algorithm_workflows"]


def get_workflow_runs_collection() -> Collection:
    """获取 workflow_runs 集合。"""
    return get_database()["workflow_runs"]


def get_algorithm_registry_entries_collection() -> Collection:
    """获取 algorithm_registry_entries 集合。"""
    return get_database()["algorithm_registry_entries"]


def get_agent_tool_policies_collection() -> Collection:
    """获取 agent_tool_policies 集合。"""
    return get_database()["agent_tool_policies"]


def get_assistant_tool_calls_collection() -> Collection:
    """获取 assistant_tool_calls 集合。"""
    return get_database()["assistant_tool_calls"]


def get_assistant_chats_collection() -> Collection:
    """获取 assistant_chats 集合。"""
    return get_database()["assistant_chats"]


def get_assistant_messages_collection() -> Collection:
    """获取 assistant_messages 集合。"""
    return get_database()["assistant_messages"]


def get_assistant_runs_collection() -> Collection:
    """获取 assistant_runs 集合。"""
    return get_database()["assistant_runs"]


def get_assistant_events_collection() -> Collection:
    """获取 assistant_events append-only 事件集合。"""
    return get_database()["assistant_events"]


def get_algorithm_packages_collection() -> Collection:
    """获取 algorithm_packages 集合。"""
    return get_database()["algorithm_packages"]


def get_algorithm_versions_collection() -> Collection:
    """获取 algorithm_versions 集合。"""
    return get_database()["algorithm_versions"]


def get_algorithm_resources_collection() -> Collection:
    """获取 algorithm_resources 集合。"""
    return get_database()["algorithm_resources"]


def get_algorithm_runs_collection() -> Collection:
    """获取 algorithm_runs 集合。"""
    return get_database()["algorithm_runs"]


def get_experiment_dispatches_collection() -> Collection:
    """获取 experiment_dispatches 集合。"""
    return get_database()["experiment_dispatches"]


def get_experiment_dispatch_profiles_collection() -> Collection:
    """获取 experiment_dispatch_profiles 集合。"""
    return get_database()["experiment_dispatch_profiles"]


def get_experiment_dispatch_targets_collection() -> Collection:
    """获取 experiment_dispatch_targets 集合。"""
    return get_database()["experiment_dispatch_targets"]


def get_algorithm_handoffs_collection() -> Collection:
    """获取 algorithm_handoffs 集合。"""
    return get_database()["algorithm_handoffs"]


def get_research_runs_collection() -> Collection:
    """获取 research_runs 集合。"""
    return get_database()["research_runs"]


def get_report_jobs_collection() -> Collection:
    """获取 report_jobs 集合。"""
    return get_database()["report_jobs"]


def get_report_artifacts_collection() -> Collection:
    """获取 report_artifacts 集合。"""
    return get_database()["report_artifacts"]


def get_alchemist_sessions_collection() -> Collection:
    """获取 alchemist_sessions 集合。"""
    return get_database()["alchemist_sessions"]
