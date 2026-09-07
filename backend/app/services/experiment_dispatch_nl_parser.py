"""实验下发自然语言参数解析器。

解析器只负责把自然语言转换为 ``manual_values`` 候选，不直接生成 payload，
也不解释任何新的执行操作符；最终仍由声明式 profile 引擎执行安全校验。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from app.schemas.experiment_dispatch_profile import (
    AtomicIntent,
    DispatchTargetDefinition,
    ExperimentDispatchProfile,
    NLDispatchParseResult,
    NLDispatchProfileCandidate,
)


@dataclass(frozen=True)
class _FieldDescriptor:
    """单个可人工覆盖字段的解析描述。"""

    path: str
    label: str
    value_type: str
    unit: str | None
    aliases: tuple[str, ...]


_SYNONYMS: dict[str, tuple[str, ...]] = {
    "experiment_name": ("实验名称", "实验名", "experiment name"),
    "experiment_content": ("实验说明", "实验备注", "备注", "说明", "experiment content"),
    "temperature": ("反应温度", "温度", "temperature"),
    "reaction_time": ("反应时间", "持续时间", "reaction time"),
    "solvent_volume": ("溶剂体积", "溶剂量", "solvent volume"),
}

_SEPARATOR = ";；，,。\n"
_ASSIGNMENT = r"(?:设为|设置为|改成|改为|为|是|to|:|：|=)"


class NLDispatchParser:
    """基于字段语义和单位规则的自然语言解析器。"""

    @staticmethod
    def parse(
        text: str,
        profiles: Sequence[ExperimentDispatchProfile],
        targets: dict[str, DispatchTargetDefinition] | None = None,
    ) -> NLDispatchParseResult:
        """解析自然语言并推荐最匹配的下发配置。

        Args:
            text: 用户输入的自然语言参数描述。
            profiles: 可访问的下发配置候选，应已由服务层完成权限过滤。
            targets: target_id@version 到目标契约的映射，用于补充字段类型和单位。

        Returns:
            原子意图、未解析意图、manual_values 候选与 profile 推荐结果。
        """
        raw_text = str(text or "").strip()
        if not raw_text:
            raise ValueError("natural_language 不能为空")
        if not profiles:
            raise ValueError("没有可用的实验下发配置")

        target_map = targets or {}
        candidates: list[tuple[float, ExperimentDispatchProfile, dict[str, Any]]] = []
        for profile in profiles:
            descriptors = NLDispatchParser._field_descriptors(profile, target_map)
            matches = NLDispatchParser._match_fields(raw_text, descriptors)
            score = NLDispatchParser._profile_score(raw_text, profile, matches)
            candidates.append((score, profile, matches))

        candidates.sort(key=lambda item: (-item[0], item[1].profile_id, item[1].version))
        _, selected_profile, selected_matches = candidates[0]
        selected_paths = set(selected_matches)
        intents: list[AtomicIntent] = []
        manual_values: dict[str, Any] = {}

        descriptors = NLDispatchParser._field_descriptors(selected_profile, target_map)
        for descriptor in descriptors:
            if descriptor.path not in selected_matches:
                continue
            value, unit, confidence = selected_matches[descriptor.path]
            manual_values[descriptor.path] = value
            intents.append(
                AtomicIntent(
                    intent_id=f"intent_{len(intents) + 1:03d}",
                    description=f"设置{descriptor.label}为 {value}",
                    target_path=descriptor.path,
                    value=value,
                    unit=unit,
                    confidence=confidence,
                    resolved=True,
                )
            )

        unresolved = NLDispatchParser._unresolved_intents(raw_text, descriptors, selected_paths)
        profile_candidates = [
            NLDispatchProfileCandidate(
                profile_id=profile.profile_id,
                profile_version=profile.version,
                score=score,
                matched_paths=[
                    item.path for item in NLDispatchParser._field_descriptors(profile, target_map)
                    if item.path in matches
                ],
            )
            for score, profile, matches in candidates[:100]
        ]

        return NLDispatchParseResult(
            raw_text=raw_text,
            intents=intents,
            unresolved=unresolved,
            manual_values=manual_values,
            profile_id=selected_profile.profile_id,
            profile_version=selected_profile.version,
            profile_candidates=profile_candidates,
        )

    @staticmethod
    def _field_descriptors(
        profile: ExperimentDispatchProfile,
        targets: dict[str, DispatchTargetDefinition],
    ) -> list[_FieldDescriptor]:
        """构建当前 profile 中允许人工覆盖的字段描述。

        Args:
            profile: 下发配置。
            targets: 目标契约映射。

        Returns:
            可安全映射到 manual_values 的字段描述列表。
        """
        target = targets.get(f"{profile.target_id}@{profile.target_version}")
        target_fields = {
            item.path: item
            for item in (profile.target_fields or target.fields if target else profile.target_fields)
        }
        descriptors: list[_FieldDescriptor] = []
        seen: set[str] = set()
        for mapping in profile.mappings:
            field = target_fields.get(mapping.target_path)
            target_allows = bool(field and field.allow_override)
            if not (mapping.allow_override or target_allows):
                continue
            path = mapping.target_path
            if path in seen:
                continue
            leaf = path.rsplit("/", 1)[-1]
            label = mapping.label or (field.label if field else None) or leaf
            manual_key = mapping.source.key if mapping.source.kind == "manual" else None
            aliases = NLDispatchParser._aliases(leaf, label, manual_key)
            descriptors.append(
                _FieldDescriptor(
                    path=path,
                    label=label,
                    value_type=(field.value_type if field else "any"),
                    unit=(field.unit if field else None),
                    aliases=aliases,
                )
            )
            seen.add(path)
        return descriptors

    @staticmethod
    def _aliases(leaf: str, label: str | None, manual_key: str | None) -> tuple[str, ...]:
        """生成字段别名并按长度降序排列。

        Args:
            leaf: JSON Pointer 最后一段字段名。
            label: 配置中的字段显示名。
            manual_key: manual 数据源的显式 key。

        Returns:
            去重后的字段别名元组。
        """
        normalized = leaf.replace("-", "_").lower()
        values = {label or "", leaf, normalized, normalized.replace("_", " "), manual_key or ""}
        values.update(_SYNONYMS.get(normalized, ()))
        aliases = tuple(item for item in values if item)
        return tuple(sorted(aliases, key=lambda item: (-len(item), item)))

    @staticmethod
    def _match_fields(text: str, descriptors: Sequence[_FieldDescriptor]) -> dict[str, Any]:
        """在自然语言中解析所有可覆盖字段。

        Args:
            text: 用户输入的自然语言。
            descriptors: 可覆盖字段描述。

        Returns:
            target_path 到 (value, unit, confidence) 的映射。
        """
        normalized_text = text.strip()
        matches: dict[str, Any] = {}
        for descriptor in descriptors:
            for alias in descriptor.aliases:
                escaped = re.escape(alias.lower())
                if descriptor.value_type in {"number", "integer"}:
                    value = NLDispatchParser._match_number(
                        normalized_text,
                        escaped,
                        descriptor.unit,
                        descriptor.value_type,
                    )
                else:
                    value = NLDispatchParser._match_value(normalized_text, escaped, descriptor.value_type)
                if value is not None:
                    parsed_value, unit, confidence = value
                    matches[descriptor.path] = (parsed_value, unit, confidence)
                    break
        return matches

    @staticmethod
    def _match_number(
        text: str,
        alias_pattern: str,
        target_unit: str | None,
        value_type: str,
    ) -> tuple[Any, str | None, float] | None:
        """解析数值字段并按目标单位归一。

        Args:
            text: 小写化后的自然语言。
            alias_pattern: 已转义的字段别名。
            target_unit: 目标契约声明的单位。
            value_type: integer 或 number。

        Returns:
            解析后的值、规范单位和置信度；未命中返回 None。
        """
        unit_group = (
            r"(?:\s*(℃|°c|摄氏度|度|c|f|k|小时|h|hour|hr|分钟|min|秒|s|天|d|"
            r"µl|μl|ul|ml|毫升|l|升)?)"
        )
        pattern = re.compile(
            rf"(?<![a-z0-9_]){alias_pattern}\s*(?:{_ASSIGNMENT})?\s*"
            rf"([-+]?\d+(?:\.\d+)?)\s*{unit_group}(?![a-z0-9])",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None
        raw_value = float(match.group(1))
        raw_unit = match.group(2) or ""
        value, unit = NLDispatchParser._normalize_number(raw_value, raw_unit, target_unit)
        if value_type == "integer":
            if not float(value).is_integer():
                return None
            value = int(value)
        return value, unit, 0.95

    @staticmethod
    def _match_value(
        text: str,
        alias_pattern: str,
        value_type: str,
    ) -> tuple[Any, str | None, float] | None:
        """解析字符串、布尔和 JSON 结构字段。

        Args:
            text: 小写化后的自然语言。
            alias_pattern: 已转义的字段别名。
            value_type: 目标字段类型。

        Returns:
            解析后的值、单位和置信度；未命中返回 None。
        """
        pattern = re.compile(
            rf"(?<![a-z0-9_]){alias_pattern}\s*{_ASSIGNMENT}\s*([^{_SEPARATOR}]+)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if not match:
            return None
        raw_value = match.group(1).strip().strip("\"'“”‘’")
        if value_type == "boolean":
            normalized = raw_value.lower()
            if normalized in {"true", "yes", "1", "开启", "是"}:
                return True, None, 0.95
            if normalized in {"false", "no", "0", "关闭", "否"}:
                return False, None, 0.95
            return None
        if value_type in {"object", "array"}:
            try:
                return json.loads(raw_value), None, 0.85
            except ValueError:
                return None
        return raw_value, None, 0.85

    @staticmethod
    def _normalize_number(
        value: float,
        raw_unit: str,
        target_unit: str | None,
    ) -> tuple[float | int, str | None]:
        """把常见温度、时间和体积单位归一到目标契约单位。

        Args:
            value: 自然语言中的数值。
            raw_unit: 自然语言中的单位原文。
            target_unit: 目标契约单位。

        Returns:
            归一后的数值与单位。
        """
        unit = raw_unit.strip().lower()
        if unit in {"℃", "°c", "c", "度", "摄氏度"}:
            source = "degC"
        elif unit == "f":
            source = "degF"
        elif unit == "k":
            source = "K"
        elif unit in {"h", "hour", "hr", "小时"}:
            source = "h"
        elif unit in {"min", "分钟"}:
            source = "min"
        elif unit in {"s", "秒"}:
            source = "s"
        elif unit in {"d", "天"}:
            source = "d"
        elif unit in {"ml", "毫升"}:
            source = "mL"
        elif unit in {"l", "升"}:
            source = "L"
        elif unit in {"µl", "μl", "ul"}:
            source = "uL"
        else:
            return value, target_unit

        target = (target_unit or "").strip()
        if target == "degC":
            if source == "degF":
                return (value - 32.0) * 5.0 / 9.0, target
            if source == "K":
                return value - 273.15, target
            return value, target
        if target == "h":
            factors = {"min": 1.0 / 60.0, "s": 1.0 / 3600.0, "d": 24.0}
            return value * factors.get(source, 1.0), target
        if target == "mL":
            factors = {"L": 1000.0, "uL": 1.0 / 1000.0}
            return value * factors.get(source, 1.0), target
        return value, source

    @staticmethod
    def _profile_score(
        text: str,
        profile: ExperimentDispatchProfile,
        matches: dict[str, Any],
    ) -> float:
        """计算 profile 与自然语言的匹配分。

        Args:
            text: 用户输入的自然语言。
            profile: 候选下发配置。
            matches: 当前 profile 已解析的字段结果。

        Returns:
            字段匹配分，保留一位小数以避免浮点排序抖动。
        """
        confidence_score = sum(item[2] for item in matches.values())
        normalized = text.lower()
        context_words = [
            profile.profile_id.lower(),
            profile.name.lower(),
            *(re.findall(r"[a-z][a-z0-9_-]{2,}", profile.name.lower())),
        ]
        context_score = sum(0.5 for item in context_words if item and item in normalized)
        return round(confidence_score + context_score, 2)

    @staticmethod
    def _unresolved_intents(
        text: str,
        descriptors: Sequence[_FieldDescriptor],
        selected_paths: set[str],
    ) -> list[AtomicIntent]:
        """提取无法映射到可覆盖字段的参数片段。

        Args:
            text: 用户输入的自然语言。
            descriptors: 已选 profile 的可覆盖字段。
            selected_paths: 已成功解析的字段路径。

        Returns:
            需要人工确认的未解析原子意图列表。
        """
        aliases = [
            alias.lower()
            for item in descriptors
            if item.path in selected_paths
            for alias in item.aliases
        ]
        unresolved: list[AtomicIntent] = []
        segments = re.split(r"[;；，,。\n]", text)
        for segment in segments:
            clause = segment.strip()
            if not clause:
                continue
            lowered = clause.lower()
            if any(alias in lowered for alias in aliases):
                continue
            has_assignment = bool(re.search(r"(?:=|:|：|为|是|设为|设置为)\s*\S+", clause))
            has_quantity = bool(
                re.search(
                    r"[-+]?\d+(?:\.\d+)?\s*(?:mpa|kpa|bar|atm|pa|m|ml|l|s|min|h|℃|°c|c|f|k)",
                    clause,
                    re.IGNORECASE,
                )
            )
            if not (has_assignment or has_quantity):
                continue
            unresolved.append(
                AtomicIntent(
                    intent_id=f"unresolved_{len(unresolved) + 1:03d}",
                    description=clause,
                    confidence=0.3,
                    resolved=False,
                )
            )
        return unresolved
