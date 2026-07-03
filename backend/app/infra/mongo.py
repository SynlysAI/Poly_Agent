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
    """获取统一认证（AI4MS）MongoDB 客户端单例。

    优先使用 AUTH_MONGODB_URI，未配置时回退到业务 MongoDB 连接。
    """
    uri = settings.auth_mongodb_uri or settings.mongodb_uri
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def _get_auth_database() -> Database:
    """获取统一认证（AI4MS）数据库对象。"""
    return _get_auth_client()[settings.auth_database]


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


def get_audit_events_collection() -> Collection:
    """获取 audit_events 集合。"""
    return get_database()["audit_events"]
