"""ALchemist 实验设计与优化工具 — 原生 API 路由。

返回格式与原 ALchemist API 完全兼容，前端无需改动。
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.alchemist_core.session import OptimizationSession
from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.schemas.alchemist import (
    AcquisitionRequest,
    AddCategoricalVariableRequest,
    AddDiscreteVariableRequest,
    AddExperimentRequest,
    AddExperimentsBatchRequest,
    AddIntegerVariableRequest,
    AddRealVariableRequest,
    ContourDataRequest,
    CreateSessionRequest,
    FindOptimumRequest,
    InitialDesignRequest,
    OptimalDesignInfoRequest,
    OptimalDesignRequest,
    StageExperimentsBatchRequest,
    SuggestEffectsRequest,
    TrainModelRequest,
    UpdateMetadataRequest,
)
from app.services.alchemist_service import service

logger = get_logger("poly_agent.alchemist")

router = APIRouter(tags=["ALchemist 主动学习工具"])


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    return current_user["user_id"] if current_user else "demo_user"


def _access_user_id(current_user: dict[str, str] | None) -> str | None:
    return current_user["user_id"] if current_user else None


def _is_admin(current_user: dict[str, str] | None) -> bool:
    return bool(current_user and current_user.get("role") == "admin")


# ── Session 管理 ──


@router.get("/sessions")
def list_sessions(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """列出所有 Session（返回数组，与原 ALchemist API 一致）。"""
    items, _ = service.list_sessions(
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
        page=1,
        page_size=200,
    )
    return [
        {
            "session_id": item["session_id"],
            "name": item.get("name"),
        }
        for item in items
    ]


@router.post("/sessions")
def create_session(
    payload: CreateSessionRequest = CreateSessionRequest(),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """创建新的优化 Session。"""
    data = service.create_session(
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
        created_by=_actor_user_id(current_user),
    )
    return {
        "session_id": data["session_id"],
        "created_at": data["created_at"].isoformat() if hasattr(data["created_at"], "isoformat") else str(data["created_at"]),
        "expires_at": None,
    }


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取 Session 详情（返回格式与原 ALchemist API 一致）。"""
    doc = service.get_session_detail(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return {
        "session_id": doc["session_id"],
        "created_at": doc.get("created_at", "").isoformat() if hasattr(doc.get("created_at"), "isoformat") else str(doc.get("created_at", "")),
        "last_accessed": doc.get("updated_at", "").isoformat() if hasattr(doc.get("updated_at"), "isoformat") else str(doc.get("updated_at", "")),
        "expires_at": None,
        "search_space": {
            "n_variables": doc.get("variable_count", 0),
            "variables": doc.get("variables", []),
        },
        "data": {
            "n_experiments": doc.get("experiment_count", 0),
            "has_data": doc.get("experiment_count", 0) > 0,
            "has_noise": False,
            "feature_names": [v.get("name") for v in doc.get("variables", [])],
        },
        "model": {
            "backend": doc.get("model_backend"),
            "hyperparameters": {},
            "metrics": {},
            "is_trained": doc.get("model_trained", False),
        } if doc.get("model_trained") else None,
    }


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, str]:
    """删除 Session。"""
    service.delete_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return {"message": "deleted"}


@router.post("/sessions/{session_id}/save")
def save_session_server_side(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, str]:
    """保存 Session（兼容旧 API，数据已自动持久化）。"""
    return {"message": "Session saved"}


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> Response:
    """导出 Session 为 JSON 文件下载。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        session.save_session(tmp.name)
        temp_path = tmp.name
    try:
        with open(temp_path, "r") as f:
            content = f.read()
    finally:
        Path(temp_path).unlink(missing_ok=True)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=session_{session_id}.json"},
    )


@router.post("/sessions/import")
def import_session(
    file: UploadFile = File(...),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """从 JSON 文件导入 Session。"""
    try:
        session_data = file.file.read().decode("utf-8")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write(session_data)
            temp_path = tmp.name
        try:
            loaded_session = OptimizationSession.load_session(temp_path, retrain_on_load=False)
        finally:
            Path(temp_path).unlink(missing_ok=True)

        data = service.create_session(created_by=_actor_user_id(current_user))
        new_id = data["session_id"]
        session = service.get_session(new_id, actor_user_id=_access_user_id(current_user), is_admin=True)
        session.search_space = loaded_session.search_space
        session.experiment_manager = loaded_session.experiment_manager
        session.audit_log = loaded_session.audit_log
        session.metadata.session_id = new_id
        service.save_session(new_id, session)
        return {
            "session_id": data["session_id"],
            "created_at": data["created_at"].isoformat() if hasattr(data["created_at"], "isoformat") else str(data["created_at"]),
            "expires_at": None,
        }
    except Exception as e:
        logger.error(f"Session 导入失败: {e}")
        raise HTTPException(status_code=400, detail="Session 导入失败，文件可能无效")


@router.post("/sessions/upload")
def upload_session(
    file: UploadFile = File(...),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """上传 JSON 文件恢复 Session。"""
    return import_session(file, current_user)


# ── 元数据 ──


@router.get("/sessions/{session_id}/metadata")
def get_metadata(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取 Session 元数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    meta = session.metadata
    return {
        "session_id": meta.session_id,
        "name": meta.name,
        "created_at": str(meta.created_at),
        "last_modified": str(meta.last_modified),
        "description": meta.description,
        "tags": meta.tags,
    }


@router.patch("/sessions/{session_id}/metadata")
def update_metadata(
    session_id: str,
    request: UpdateMetadataRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """更新 Session 元数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    session.update_metadata(name=request.name, description=request.description, tags=request.tags)
    service.save_session(session_id, session)
    meta = session.metadata
    return {
        "session_id": meta.session_id,
        "name": meta.name,
        "created_at": str(meta.created_at),
        "last_modified": str(meta.last_modified),
        "description": meta.description,
        "tags": meta.tags,
    }


# ── 变量管理 ──


@router.post("/sessions/{session_id}/variables")
def add_variable(
    session_id: str,
    variable: AddRealVariableRequest | AddIntegerVariableRequest | AddCategoricalVariableRequest | AddDiscreteVariableRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """添加变量到搜索空间。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    var_dict = variable.model_dump()
    var_type = var_dict.pop("type")
    name = var_dict.pop("name")

    if "categories" in var_dict:
        var_dict["values"] = var_dict.pop("categories")

    session.add_variable(name, var_type, **var_dict)
    service.save_session(session_id, session)
    return {"message": "变量添加成功", "variable": {"name": name, "type": var_type, **var_dict}}


@router.get("/sessions/{session_id}/variables")
def list_variables(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取搜索空间中所有变量。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    summary = session.get_search_space_summary()
    return {"variables": summary["variables"], "n_variables": summary["n_variables"]}


@router.put("/sessions/{session_id}/variables/{variable_name}")
def update_variable(
    session_id: str,
    variable_name: str,
    variable: AddRealVariableRequest | AddIntegerVariableRequest | AddCategoricalVariableRequest | AddDiscreteVariableRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """更新搜索空间中已有的变量。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    var_dict = variable.model_dump()
    var_type = var_dict.pop("type")
    new_name = var_dict.pop("name")

    if new_name != variable_name:
        raise HTTPException(status_code=400, detail="请求体中的变量名称必须与 URL 路径中的名称一致")

    var_index = None
    for i, var in enumerate(session.search_space.variables):
        if var["name"] == variable_name:
            var_index = i
            break
    if var_index is None:
        raise HTTPException(status_code=404, detail=f"变量 '{variable_name}' 不存在")

    if "categories" in var_dict:
        var_dict["values"] = var_dict.pop("categories")

    updated_var = {"name": variable_name, "type": var_type, **var_dict}
    session.search_space.variables[var_index] = updated_var

    if var_type == "real":
        from skopt.space import Real
        session.search_space.skopt_dimensions[var_index] = Real(var_dict["min"], var_dict["max"], name=variable_name)
    elif var_type == "integer":
        from skopt.space import Integer
        session.search_space.skopt_dimensions[var_index] = Integer(var_dict["min"], var_dict["max"], name=variable_name)
    elif var_type == "categorical":
        from skopt.space import Categorical
        session.search_space.skopt_dimensions[var_index] = Categorical(var_dict["values"], name=variable_name)
    elif var_type == "discrete":
        from skopt.space import Categorical
        sorted_vals = sorted(float(v) for v in var_dict["allowed_values"])
        var_dict["allowed_values"] = sorted_vals
        updated_var["allowed_values"] = sorted_vals
        session.search_space.skopt_dimensions[var_index] = Categorical(sorted_vals, name=variable_name)

    service.save_session(session_id, session)
    return {"message": "变量更新成功", "variable": updated_var}


@router.delete("/sessions/{session_id}/variables/{variable_name}")
def delete_variable(
    session_id: str,
    variable_name: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """从搜索空间中删除变量。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    found = False
    for i, var in enumerate(session.search_space.variables):
        if var["name"] == variable_name:
            session.search_space.variables.pop(i)
            session.search_space.skopt_dimensions.pop(i)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"变量 '{variable_name}' 不存在")
    service.save_session(session_id, session)
    summary = session.get_search_space_summary()
    return {"message": f"变量 '{variable_name}' 删除成功", "n_variables": summary["n_variables"]}


# ── 实验设计 ──


@router.post("/sessions/{session_id}/initial-design")
def generate_initial_design(
    session_id: str,
    request: InitialDesignRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """生成初始实验设计（DoE）。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if len(session.search_space.variables) == 0:
        raise HTTPException(status_code=400, detail="未定义任何变量，请先向搜索空间添加变量")

    kwargs = dict(
        method=request.method,
        random_seed=request.random_seed,
        lhs_criterion=request.lhs_criterion,
        n_levels=request.n_levels,
        n_center=request.n_center,
        generators=request.generators,
        ccd_alpha=request.ccd_alpha,
        ccd_face=request.ccd_face,
        gsd_reduction=request.gsd_reduction,
    )
    if request.n_points is not None:
        kwargs["n_points"] = request.n_points

    design_points = session.generate_initial_design(**kwargs)

    from app.alchemist_core.utils.doe import get_design_info
    design_info = get_design_info(
        method=request.method,
        search_space=session.search_space,
        n_levels=request.n_levels,
        n_center=request.n_center,
        generators=request.generators,
        ccd_alpha=request.ccd_alpha,
        ccd_face=request.ccd_face,
        gsd_reduction=request.gsd_reduction,
    )
    return {"points": design_points, "method": request.method, "n_points": len(design_points), "design_info": design_info}


# ── 实验数据 ──


@router.post("/sessions/{session_id}/experiments")
def add_experiment(
    session_id: str,
    experiment: AddExperimentRequest,
    auto_train: bool = Query(False),
    training_backend: str | None = Query(None),
    training_kernel: str | None = Query(None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """添加单个实验数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if len(session.search_space.variables) == 0:
        raise HTTPException(status_code=400, detail="未定义任何变量")

    session.add_experiment(
        inputs=experiment.inputs,
        output=experiment.output,
        noise=experiment.noise,
        iteration=experiment.iteration,
        reason=experiment.reason,
    )
    n = len(session.experiment_manager.df)

    model_trained = False
    training_metrics = None
    if auto_train and n >= 5:
        try:
            backend = training_backend or (session.model_backend if session.model else "sklearn")
            kernel = training_kernel or "rbf"
            result = session.train_model(backend=backend, kernel=kernel)
            model_trained = True
            metrics = result.get("metrics", {})
            training_metrics = {"rmse": metrics.get("rmse"), "r2": metrics.get("r2"), "backend": backend}
        except Exception as e:
            logger.error(f"自动训练失败: {e}")

    service.save_session(session_id, session)
    return {"message": "实验数据添加成功", "n_experiments": n, "model_trained": model_trained, "training_metrics": training_metrics}


@router.post("/sessions/{session_id}/experiments/batch")
def add_experiments_batch(
    session_id: str,
    batch: AddExperimentsBatchRequest,
    auto_train: bool = Query(False),
    training_backend: str | None = Query(None),
    training_kernel: str | None = Query(None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """批量添加实验数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if len(session.search_space.variables) == 0:
        raise HTTPException(status_code=400, detail="未定义任何变量")

    for exp in batch.experiments:
        session.add_experiment(inputs=exp.inputs, output=exp.output, noise=exp.noise)
    n = len(session.experiment_manager.df)

    model_trained = False
    training_metrics = None
    if auto_train and n >= 5:
        try:
            backend = training_backend or (session.model_backend if session.model else "sklearn")
            kernel = training_kernel or "rbf"
            result = session.train_model(backend=backend, kernel=kernel)
            model_trained = True
            metrics = result.get("metrics", {})
            training_metrics = {"rmse": metrics.get("rmse"), "r2": metrics.get("r2"), "backend": backend}
        except Exception as e:
            logger.error(f"自动训练失败: {e}")

    service.save_session(session_id, session)
    return {"message": f"成功添加 {len(batch.experiments)} 个实验数据", "n_experiments": n, "model_trained": model_trained, "training_metrics": training_metrics}


@router.get("/sessions/{session_id}/experiments")
def list_experiments(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取所有实验数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    df = session.experiment_manager.get_data()
    experiments = df.to_dict("records")
    return {"experiments": experiments, "n_experiments": len(experiments)}


@router.get("/sessions/{session_id}/experiments/summary")
def get_experiments_summary(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取实验数据统计摘要。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return session.get_data_summary()


@router.post("/sessions/{session_id}/experiments/preview")
def preview_csv_columns(
    session_id: str,
    file: UploadFile = File(...),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """预览 CSV 文件列。"""
    _ = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".csv") as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        df = pd.read_csv(tmp_path)
        columns = df.columns.tolist()
        has_output = "Output" in columns
        metadata_cols = {"Iteration", "Reason", "Noise"}
        available_targets = [col for col in columns if col not in metadata_cols]
        return {"columns": columns, "available_targets": available_targets, "has_output": has_output, "recommended_target": available_targets[0] if available_targets else None, "n_rows": len(df)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/sessions/{session_id}/experiments/upload")
def upload_csv_experiments(
    session_id: str,
    file: UploadFile = File(...),
    target_columns: str = "Output",
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """从 CSV 上传实验数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if len(session.search_space.variables) == 0:
        raise HTTPException(status_code=400, detail="未定义任何变量")

    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".csv") as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = tmp.name
    try:
        target_cols = target_columns.split(",") if "," in target_columns else target_columns
        session.load_data(tmp_path, target_columns=target_cols)
        n = len(session.experiment_manager.df)
        service.save_session(session_id, session)
        return {"message": f"成功加载 {n} 个实验数据", "n_experiments": n}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.delete("/sessions/{session_id}/experiments/{row_index}")
def delete_experiment(
    session_id: str,
    row_index: int,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """删除指定索引的单行实验数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if session.model is not None and session.model.is_trained:
        session.model = None
        session.model_backend = None
    if not session.experiment_manager.remove_experiment(row_index):
        raise HTTPException(status_code=404, detail=f"实验行索引 {row_index} 不存在")
    service.save_session(session_id, session)
    n = len(session.experiment_manager.df)
    return {"message": f"已删除第 {row_index + 1} 行实验数据", "n_experiments": n}


# ── 暂存实验 ──


@router.post("/sessions/{session_id}/experiments/staged/batch")
def stage_experiments_batch(
    session_id: str,
    request: StageExperimentsBatchRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """批量暂存实验。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    for inputs in request.experiments:
        inputs_with_meta = dict(inputs)
        if request.reason:
            inputs_with_meta["_reason"] = request.reason
        session.add_staged_experiment(inputs_with_meta)
    service.save_session(session_id, session)
    clean_experiments = [{k: v for k, v in d.items() if not k.startswith("_")} for d in request.experiments]
    return {"experiments": clean_experiments, "n_staged": len(session.get_staged_experiments()), "reason": request.reason}


# ── 最优设计 ──


@router.post("/sessions/{session_id}/optimal-design/info")
def get_optimal_design_info(
    session_id: str,
    request: OptimalDesignInfoRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """预览最优设计模型项。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    info = session.get_optimal_design_info(model_type=request.model_type, effects=request.effects)
    return info


@router.post("/sessions/{session_id}/optimal-design")
def generate_optimal_design(
    session_id: str,
    request: OptimalDesignRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """生成最优实验设计。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    points, info = session.generate_optimal_design(
        model_type=request.model_type,
        effects=request.effects,
        n_points=request.n_points,
        p_multiplier=request.p_multiplier,
        criterion=request.criterion,
        algorithm=request.algorithm,
        n_levels=request.n_levels,
        max_iter=request.max_iter,
        random_seed=request.random_seed,
    )
    return {"points": points, "n_points": len(points), "design_info": info}


# ── GP 建模 ──


@router.post("/sessions/{session_id}/model/train")
def train_model(
    session_id: str,
    request: TrainModelRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """训练 GP 代理模型。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if session.experiment_manager.df.empty:
        raise HTTPException(status_code=400, detail="没有可用的实验数据")

    try:
        results = session.train_model(
            backend=request.backend,
            kernel=request.kernel,
            kernel_params=request.kernel_params,
            input_transform_type=request.input_transform,
            output_transform_type=request.output_transform,
            calibration_enabled=request.calibration_enabled,
        )
        service.save_session(session_id, session)
        return {
            "success": results["success"],
            "backend": results["backend"],
            "kernel": results["kernel"],
            "hyperparameters": results["hyperparameters"],
            "metrics": results["metrics"],
            "message": "模型训练成功",
        }
    except Exception as e:
        logger.error(f"模型训练失败: {e}")
        raise HTTPException(status_code=500, detail=f"模型训练失败: {str(e)}")


@router.get("/sessions/{session_id}/model")
def get_model_info(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取模型信息。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    summary = session.get_model_summary()
    if summary is None:
        return {"backend": None, "hyperparameters": None, "metrics": None, "is_trained": False}
    return summary


# ── 采集优化 ──


@router.post("/sessions/{session_id}/acquisition/suggest")
def suggest_next_experiments(
    session_id: str,
    request: AcquisitionRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """建议下一个实验点。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if session.model is None:
        raise HTTPException(status_code=400, detail="没有已训练的模型")

    acq_kwargs = {}
    if request.xi is not None:
        acq_kwargs["xi"] = request.xi
    if request.kappa is not None:
        acq_kwargs["kappa"] = request.kappa

    suggestions_df = session.suggest_next(
        strategy=request.strategy,
        goal=request.goal,
        n_suggestions=request.n_suggestions,
        **acq_kwargs,
    )
    suggestions = suggestions_df.to_dict("records")
    session.last_suggestions = suggestions
    service.save_session(session_id, session)
    return {"suggestions": suggestions, "n_suggestions": len(suggestions)}


@router.post("/sessions/{session_id}/acquisition/find-optimum")
def find_model_optimum(
    session_id: str,
    request: FindOptimumRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """寻找模型预测最优点。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if session.model is None:
        raise HTTPException(status_code=400, detail="没有已训练的模型")

    backend = session.model_backend
    if backend == "sklearn":
        from app.alchemist_core.acquisition.skopt_acquisition import SkoptAcquisition
        acq = SkoptAcquisition(search_space=session.search_space, model=session.model, maximize=(request.goal == "maximize"), random_state=42)
        result = acq.find_optimum(model=session.model, maximize=(request.goal == "maximize"), random_state=42)
    elif backend == "botorch":
        from app.alchemist_core.acquisition.botorch_acquisition import BoTorchAcquisition
        acq = BoTorchAcquisition(search_space=session.search_space, model=session.model, acq_func="ucb", maximize=(request.goal == "maximize"), random_state=42)
        result = acq.find_optimum(model=session.model, maximize=(request.goal == "maximize"), random_state=42)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的模型后端: {backend}")

    opt_value = float(result["value"])
    opt_std = float(result["std"]) if result.get("std") is not None else None
    if opt_std is not None and (math.isnan(opt_std) or math.isinf(opt_std)):
        opt_std = None

    optimum = result["x_opt"].to_dict("records")[0]
    return {"optimum": optimum, "predicted_value": opt_value, "predicted_std": opt_std, "goal": request.goal}


# ── 可视化 ──


@router.get("/sessions/{session_id}/visualizations/parity")
def get_parity_data(
    session_id: str,
    use_calibrated: bool = Query(False),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取 Parity 图数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if not session.model or not session.model.is_trained:
        raise HTTPException(status_code=400, detail="请先训练模型")

    cv_results = (
        getattr(session.model, "cv_cached_results_calibrated", None)
        if use_calibrated
        else session.model.cv_cached_results
    )
    if cv_results is None:
        raise HTTPException(status_code=400, detail="没有缓存的交叉验证结果")

    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

    y_true = np.array(cv_results["y_true"])
    y_pred = np.array(cv_results["y_pred"])
    y_std = np.array(cv_results["y_std"])
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae = float(mean_absolute_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred))
    min_val = float(min(y_true.min(), y_pred.min()))
    max_val = float(max(y_true.max(), y_pred.max()))

    return {
        "y_true": y_true.tolist(),
        "y_pred": y_pred.tolist(),
        "y_std": y_std.tolist(),
        "metrics": {"rmse": rmse, "mae": mae, "r2": r2},
        "bounds": [min_val, max_val],
        "calibrated": bool(use_calibrated and hasattr(session.model, "cv_cached_results_calibrated")),
    }


@router.get("/sessions/{session_id}/visualizations/metrics")
def get_metrics_data(
    session_id: str,
    cv_splits: int = Query(5, ge=2, le=10),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取学习曲线指标。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if not session.model or not session.model.is_trained:
        raise HTTPException(status_code=400, detail="请先训练模型")
    if len(session.experiment_manager) == 0:
        raise HTTPException(status_code=400, detail="没有实验数据")

    metrics_dict = session.model.evaluate(session.experiment_manager, cv_splits=cv_splits, debug=False)
    n = len(session.experiment_manager.get_data())

    def sanitize(lst):
        return [None if (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else float(v) if v is not None else None for v in lst]

    return {
        "training_sizes": list(range(5, n + 1)),
        "rmse": sanitize(metrics_dict["RMSE"]),
        "mae": sanitize(metrics_dict["MAE"]),
        "r2": sanitize(metrics_dict["R²"]),
        "mape": sanitize(metrics_dict["MAPE"]),
    }


@router.get("/sessions/{session_id}/visualizations/qq-plot")
def get_qq_plot_data(
    session_id: str,
    use_calibrated: bool = Query(False),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取 Q-Q 图数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if not session.model or not session.model.is_trained:
        raise HTTPException(status_code=400, detail="请先训练模型")

    cv_results = (
        getattr(session.model, "cv_cached_results_calibrated", None)
        if use_calibrated
        else session.model.cv_cached_results
    )
    if cv_results is None:
        raise HTTPException(status_code=400, detail="没有缓存的交叉验证结果")

    from scipy import stats

    y_true = np.array(cv_results["y_true"])
    y_pred = np.array(cv_results["y_pred"])
    y_std = np.array(cv_results["y_std"])
    z_scores = (y_true - y_pred) / y_std
    z_sorted = np.sort(z_scores)
    theoretical = stats.norm.ppf(np.linspace(0.01, 0.99, len(z_scores)))
    min_v = float(min(theoretical.min(), z_sorted.min()))
    max_v = float(max(theoretical.max(), z_sorted.max()))

    return {
        "theoretical_quantiles": theoretical.tolist(),
        "sample_quantiles": z_sorted.tolist(),
        "z_mean": float(np.mean(z_scores)),
        "z_std": float(np.std(z_scores, ddof=1)),
        "n_samples": int(len(z_scores)),
        "bounds": [min_v, max_v],
        "calibrated": bool(use_calibrated),
    }


@router.get("/sessions/{session_id}/visualizations/calibration-curve")
def get_calibration_curve_data(
    session_id: str,
    use_calibrated: bool = Query(False),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取校准曲线数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if not session.model or not session.model.is_trained:
        raise HTTPException(status_code=400, detail="请先训练模型")

    cv_results = (
        getattr(session.model, "cv_cached_results_calibrated", None)
        if use_calibrated
        else session.model.cv_cached_results
    )
    if cv_results is None:
        raise HTTPException(status_code=400, detail="没有缓存的交叉验证结果")

    from scipy import stats

    y_true = np.array(cv_results["y_true"])
    y_pred = np.array(cv_results["y_pred"])
    y_std = np.array(cv_results["y_std"])
    nominal = np.arange(0.10, 1.00, 0.05)
    empirical = []
    labels = []
    for prob in nominal:
        m = stats.norm.ppf((1 + prob) / 2)
        labels.append(f"±{m:.2f}σ ({int(prob * 100)}%)")
        lb = y_pred - m * y_std
        ub = y_pred + m * y_std
        empirical.append(float(np.mean((y_true >= lb) & (y_true <= ub))))

    return {
        "nominal_coverage": nominal.tolist(),
        "empirical_coverage": empirical,
        "confidence_levels": labels,
        "nominal_probabilities": nominal.tolist(),
        "empirical_probabilities": empirical,
        "n_samples": int(len(y_true)),
        "calibrated": bool(use_calibrated),
        "results_type": "calibrated" if use_calibrated else "uncalibrated",
    }


@router.get("/sessions/{session_id}/visualizations/hyperparameters")
def get_hyperparameters(
    session_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取模型超参数。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if not session.model or not session.model.is_trained:
        raise HTTPException(status_code=400, detail="请先训练模型")

    raw = session.model.get_hyperparameters()
    hyperparams = {}
    for k, v in raw.items():
        try:
            json.dumps(v)
            hyperparams[k] = v
        except (TypeError, ValueError):
            hyperparams[k] = str(v)

    return {
        "hyperparameters": hyperparams,
        "backend": "sklearn" if hasattr(session.model, "model") else "botorch",
        "kernel": getattr(session.model, "kernel_type", "unknown"),
        "input_transform": getattr(session.model, "input_transform_type", None),
        "output_transform": getattr(session.model, "output_transform_type", None),
        "calibration_enabled": getattr(session.model, "calibration_enabled", False),
        "calibration_factor": float(getattr(session.model, "calibration_factor", None)) if getattr(session.model, "calibration_factor", None) is not None else None,
    }


@router.post("/sessions/{session_id}/visualizations/contour")
def get_contour_data(
    session_id: str,
    request: ContourDataRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """获取等值线图数据。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    if not session.model or not session.model.is_trained:
        raise HTTPException(status_code=400, detail="请先训练模型")

    var_names = session.search_space.get_variable_names()
    if request.x_var not in var_names or request.y_var not in var_names:
        raise HTTPException(status_code=400, detail="变量不存在于搜索空间中")
    if request.x_var == request.y_var:
        raise HTTPException(status_code=400, detail="X 和 Y 变量必须不同")

    x_info = next(v for v in session.search_space.variables if v["name"] == request.x_var)
    y_info = next(v for v in session.search_space.variables if v["name"] == request.y_var)
    x_bounds = (x_info["min"], x_info["max"])
    y_bounds = (y_info["min"], y_info["max"])

    x_range = np.linspace(x_bounds[0], x_bounds[1], request.grid_resolution)
    y_range = np.linspace(y_bounds[0], y_bounds[1], request.grid_resolution)
    X_grid, Y_grid = np.meshgrid(x_range, y_range)

    filtered_fixed = {k: v for k, v in request.fixed_values.items() if k != request.x_var and k != request.y_var}
    grid_points = []
    for i in range(request.grid_resolution):
        for j in range(request.grid_resolution):
            point = filtered_fixed.copy()
            point[request.x_var] = X_grid[i, j]
            point[request.y_var] = Y_grid[i, j]
            for var in session.search_space.variables:
                if var["name"] not in point:
                    if var["type"] in ["real", "integer"]:
                        point[var["name"]] = (var["min"] + var["max"]) / 2.0
                    elif var["type"] == "categorical":
                        point[var["name"]] = var["values"][0]
                    elif var["type"] == "discrete":
                        av = var["allowed_values"]
                        point[var["name"]] = av[len(av) // 2]
            grid_points.append(point)

    grid_df = pd.DataFrame(grid_points)
    train_data = session.experiment_manager.get_data()
    target_cols = set(session.experiment_manager.target_columns)
    metadata_cols = {"Iteration", "Reason", "Noise"} | target_cols
    feature_cols = [col for col in train_data.columns if col not in metadata_cols]
    grid_df = grid_df.reindex(columns=feature_cols)

    predictions, uncertainties = session.model.predict(grid_df, return_std=True)
    pred_grid = predictions.reshape((request.grid_resolution, request.grid_resolution))
    unc_grid = uncertainties.reshape((request.grid_resolution, request.grid_resolution))

    experiments_data = None
    if request.include_experiments and len(session.experiment_manager) > 0:
        exp_df = session.experiment_manager.get_data()
        target_col = session.experiment_manager.target_columns[0]
        if request.x_var in exp_df.columns and request.y_var in exp_df.columns and target_col in exp_df.columns:
            experiments_data = {"x": exp_df[request.x_var].tolist(), "y": exp_df[request.y_var].tolist(), "output": exp_df[target_col].tolist()}

    return {
        "x_var": request.x_var,
        "y_var": request.y_var,
        "x_grid": X_grid.tolist(),
        "y_grid": Y_grid.tolist(),
        "predictions": pred_grid.tolist(),
        "uncertainties": unc_grid.tolist(),
        "experiments": experiments_data,
        "x_bounds": [float(x_bounds[0]), float(x_bounds[1])],
        "y_bounds": [float(y_bounds[0]), float(y_bounds[1])],
        "colorbar_bounds": [float(pred_grid.min()), float(pred_grid.max())],
    }


# ── LLM 辅助 ──


@router.post("/llm/suggest-effects/{session_id}")
async def suggest_effects_sse(
    session_id: str,
    request: SuggestEffectsRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
):
    """SSE 流式返回 LLM 效应建议。"""
    session = service.get_session(
        session_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    variables = session.search_space.variables
    if not variables:
        raise HTTPException(status_code=400, detail="搜索空间中未定义变量")

    from app.services.alchemist_llm_service import suggest_effects_stream

    return StreamingResponse(
        suggest_effects_stream(variables, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
