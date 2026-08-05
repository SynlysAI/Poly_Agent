"""声明式实验下发配置执行器。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.schemas.experiment_dispatch_profile import (
    DispatchCondition,
    DispatchEvaluationResult,
    DispatchMappingTrace,
    DispatchTargetDefinition,
    DispatchTransform,
    DispatchValueSource,
    ExperimentDispatchProfile,
)


_MISSING = object()


class ExperimentDispatchProfileEngine:
    """只解释固定操作符，不执行领域代码或用户脚本。"""

    def evaluate(
        self,
        profile: ExperimentDispatchProfile,
        target: DispatchTargetDefinition,
        input_snapshot: dict[str, Any],
        output_summary: dict[str, Any],
        run_metadata: dict[str, Any],
        manual_values: dict[str, Any],
    ) -> DispatchEvaluationResult:
        context = {
            "input": deepcopy(input_snapshot),
            "output": deepcopy(output_summary),
            "run": deepcopy(run_metadata),
            "manual": deepcopy(manual_values),
            "target": {},
        }
        payload: dict[str, Any] = context["target"]
        trace: list[DispatchMappingTrace] = []
        warnings: list[str] = []
        errors: list[str] = []

        self._validate_source_contract(profile, context, errors)
        target_fields = {item.path: item for item in target.fields}

        for mapping in profile.mappings:
            value, source_label = self._resolve_source(mapping.source, context)
            overridden = False
            if value is not _MISSING:
                value = self._apply_transforms(value, mapping.transforms, errors, mapping.target_path)
            manual_value = self._manual_override(manual_values, mapping.target_path)
            allow_override = mapping.allow_override or bool(target_fields.get(mapping.target_path) and target_fields[mapping.target_path].allow_override)
            if allow_override and manual_value is not _MISSING:
                value = manual_value
                source_label = f"/manual{mapping.target_path}"
                overridden = True
            if value is _MISSING and mapping.default_value is not None:
                value = deepcopy(mapping.default_value)
                source_label = "default_value"
            if value is _MISSING:
                self._handle_missing(mapping.target_path, mapping.required, mapping.error_policy, warnings, errors)
                continue
            self.set_pointer(payload, mapping.target_path, value)
            trace.append(DispatchMappingTrace(
                target_path=mapping.target_path,
                source=source_label,
                value=deepcopy(value),
                transforms=[item.operation for item in mapping.transforms],
                overridden=overridden,
            ))

        matched_rules: list[str] = []
        for branch in sorted(profile.branches, key=lambda item: item.priority):
            matches = [self._condition_matches(item, context) for item in branch.conditions.items]
            if not (all(matches) if branch.conditions.mode == "all" else any(matches)):
                continue
            matched_rules.append(branch.rule_id)
            for action in branch.actions:
                if action.kind == "warn":
                    warnings.append(action.message or "")
                    continue
                if action.kind == "block":
                    errors.append(action.message or "")
                    continue
                value, source_label = self._resolve_source(action.source, context)
                if value is _MISSING:
                    errors.append(f"规则 {branch.name} 无法解析目标 {action.target_path} 的值")
                    continue
                value = self._apply_transforms(value, action.transforms, errors, action.target_path or "")
                if value is _MISSING:
                    continue
                self.set_pointer(payload, action.target_path or "", value)
                trace.append(DispatchMappingTrace(
                    target_path=action.target_path or "",
                    source=source_label,
                    value=deepcopy(value),
                    transforms=[item.operation for item in action.transforms],
                    rule_id=branch.rule_id,
                ))
            if branch.stop_on_match:
                break

        self._validate_target(target, payload, errors)
        return DispatchEvaluationResult(
            payload=payload,
            trace=trace,
            matched_rules=matched_rules,
            warnings=[item for item in warnings if item],
            errors=[item for item in errors if item],
            is_valid=not errors,
        )

    def _validate_source_contract(self, profile, context, errors) -> None:
        for field in profile.source_contract.required_fields:
            value = self.resolve_pointer(context, field.path)
            if value is _MISSING:
                if field.required:
                    errors.append(f"缺少算法输出字段 {field.path}")
                continue
            if not self._matches_type(value, field.value_type):
                errors.append(f"算法输出字段 {field.path} 类型应为 {field.value_type}")

    @staticmethod
    def _manual_override(manual_values: dict[str, Any], target_path: str):
        if target_path in manual_values:
            return manual_values[target_path]
        key = target_path.rsplit("/", 1)[-1]
        return manual_values.get(key, _MISSING)

    def _resolve_source(self, source: DispatchValueSource | None, context: dict[str, Any]):
        if source is None:
            return _MISSING, None
        if source.kind == "constant":
            return deepcopy(source.value), "constant"
        if source.kind == "manual":
            return context["manual"].get(source.key, _MISSING), f"/manual/{source.key}"
        if source.kind == "coalesce":
            for path in source.paths:
                value = self.resolve_pointer(context, path)
                if value is not _MISSING and value is not None:
                    return deepcopy(value), path
            return _MISSING, None
        path = source.path or ""
        if source.kind == "target" and not path.startswith("/target"):
            path = f"/target{path}"
        return deepcopy(self.resolve_pointer(context, path)), path

    def _apply_transforms(self, value, transforms: list[DispatchTransform], errors: list[str], target_path: str):
        current = value
        try:
            for transform in transforms:
                if transform.operation == "default":
                    if current is None or current == "":
                        current = deepcopy(transform.default_value)
                elif transform.operation == "cast":
                    current = self._cast(current, transform.value_type or "any")
                elif transform.operation == "scale":
                    if isinstance(current, bool) or not isinstance(current, (int, float)):
                        raise ValueError("scale 仅支持数值")
                    current = current * transform.scale + transform.offset
                elif transform.operation == "lookup":
                    key = str(current)
                    if key not in transform.lookup:
                        if transform.default_value is None:
                            raise ValueError(f"lookup 不包含 {key}")
                        current = deepcopy(transform.default_value)
                    else:
                        current = deepcopy(transform.lookup[key])
                elif transform.operation == "concat":
                    current = f"{transform.prefix}{current}{transform.suffix}"
                elif transform.operation == "array_item":
                    if not isinstance(current, list):
                        raise ValueError("array_item 仅支持数组")
                    current = current[transform.index]
            return current
        except (TypeError, ValueError, IndexError) as exc:
            errors.append(f"目标字段 {target_path} 转换失败：{exc}")
            return _MISSING

    def _condition_matches(self, condition: DispatchCondition, context: dict[str, Any]) -> bool:
        value = self.resolve_pointer(context, condition.path)
        if condition.operator == "exists":
            return (value is not _MISSING) == bool(condition.value if condition.value is not None else True)
        if value is _MISSING:
            return False
        expected = condition.value
        try:
            return {
                "equals": lambda: value == expected,
                "notEquals": lambda: value != expected,
                "in": lambda: value in expected,
                "between": lambda: expected[0] <= value <= expected[1],
                "gt": lambda: value > expected,
                "gte": lambda: value >= expected,
                "lt": lambda: value < expected,
                "lte": lambda: value <= expected,
            }[condition.operator]()
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _handle_missing(path: str, required: bool, policy: str, warnings: list[str], errors: list[str]) -> None:
        if not required or policy == "omit":
            return
        message = f"无法解析必填目标字段 {path}"
        (warnings if policy == "warn" else errors).append(message)

    def _validate_target(self, target: DispatchTargetDefinition, payload: dict[str, Any], errors: list[str]) -> None:
        for field in target.fields:
            value = self.resolve_pointer(payload, field.path)
            if value is _MISSING and field.default_value is not None:
                self.set_pointer(payload, field.path, deepcopy(field.default_value))
                value = field.default_value
            if value is _MISSING:
                if field.required:
                    errors.append(f"目标接口缺少必填字段 {field.path}")
                continue
            if not self._matches_type(value, field.value_type):
                errors.append(f"目标字段 {field.path} 类型应为 {field.value_type}")

    @staticmethod
    def _cast(value: Any, value_type: str):
        if value_type == "string":
            return str(value)
        if value_type == "number":
            return float(value)
        if value_type == "integer":
            return int(value)
        if value_type == "boolean":
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes"}:
                    return True
                if normalized in {"false", "0", "no"}:
                    return False
                raise ValueError("无法转换为 boolean")
            return bool(value)
        if value_type == "array" and not isinstance(value, list):
            return [value]
        if value_type == "object" and not isinstance(value, dict):
            raise ValueError("无法转换为 object")
        return value

    @staticmethod
    def _matches_type(value: Any, value_type: str) -> bool:
        return {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "any": True,
        }[value_type]

    @staticmethod
    def resolve_pointer(document: Any, pointer: str):
        if pointer == "":
            return document
        if not pointer.startswith("/"):
            return _MISSING
        current = document
        for raw_part in pointer[1:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return _MISSING
        return current

    @staticmethod
    def set_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
        parts = [item.replace("~1", "/").replace("~0", "~") for item in pointer[1:].split("/")]
        current = document
        for part in parts[:-1]:
            nested = current.get(part)
            if not isinstance(nested, dict):
                nested = {}
                current[part] = nested
            current = nested
        current[parts[-1]] = deepcopy(value)


experiment_dispatch_profile_engine = ExperimentDispatchProfileEngine()
