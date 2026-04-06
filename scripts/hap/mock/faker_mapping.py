#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Faker 造数映射表：根据字段名和字段类型生成模拟数据。
优先级：字段名精确匹配 > 字段名模糊匹配 > 单选/多选选项 > 字段类型兜底。
"""

from __future__ import annotations

import random
from typing import Any, Optional

from faker import Faker

faker = Faker("zh_CN")

# ============================================================
# 1. 字段名精确匹配表（中文）
# ============================================================
_EXACT_NAME_GENERATORS: dict[str, callable] = {
    "姓名": lambda: faker.name(),
    "名称": lambda: faker.name(),
    "联系人": lambda: faker.name(),
    "手机号": lambda: faker.phone_number(),
    "手机": lambda: faker.phone_number(),
    "电话": lambda: faker.phone_number(),
    "联系电话": lambda: faker.phone_number(),
    "邮箱": lambda: faker.email(),
    "电子邮箱": lambda: faker.email(),
    "Email": lambda: faker.email(),
    "地址": lambda: faker.address(),
    "详细地址": lambda: faker.address(),
    "联系地址": lambda: faker.address(),
    "公司": lambda: faker.company(),
    "公司名称": lambda: faker.company(),
    "企业名称": lambda: faker.company(),
    "部门": lambda: random.choice(["销售部", "市场部", "研发部", "财务部", "人事部", "运营部", "技术部", "客服部"]),
    "所属部门": lambda: random.choice(["销售部", "市场部", "研发部", "财务部", "人事部", "运营部", "技术部", "客服部"]),
    "职位": lambda: faker.job(),
    "岗位": lambda: faker.job(),
    "身份证": lambda: faker.ssn(),
    "身份证号": lambda: faker.ssn(),
    "网址": lambda: faker.url(),
    "网站": lambda: faker.url(),
    "链接": lambda: faker.url(),
    "描述": lambda: faker.paragraph(nb_sentences=2),
    "说明": lambda: faker.paragraph(nb_sentences=2),
    "备注": lambda: faker.paragraph(nb_sentences=2),
    "详情": lambda: faker.paragraph(nb_sentences=2),
}

# ============================================================
# 2. 字段名模糊匹配规则（contains 关键词 → 生成器）
# ============================================================
_FUZZY_NAME_RULES: list[tuple[list[str], callable]] = [
    (["日期", "时间"], lambda: faker.date_between(start_date="-1y", end_date="today").isoformat()),
    (["金额", "费用", "价格", "单价", "总价", "成本"], lambda: round(random.uniform(100, 99999), 2)),
    (["数量", "个数", "人数", "次数"], lambda: random.randint(1, 1000)),
    (["比例", "占比", "百分比", "进度", "完成率"], lambda: round(random.uniform(0, 100), 1)),
    (["编号", "编码", "代码"], lambda: f"{faker.random_uppercase_letter()}{faker.random_uppercase_letter()}-{faker.random_int(min=1000, max=9999)}"),
]

# ============================================================
# 3. 单选/多选字段类型集合
# ============================================================
_OPTION_FIELD_TYPES = {"SingleSelect", "MultipleSelect", "Dropdown"}

# ============================================================
# 4. 字段类型兜底映射
# ============================================================
_TYPE_GENERATORS: dict[str, callable] = {
    "Text": lambda: faker.sentence(),
    "Number": lambda: round(random.uniform(1, 10000), 2),
    "Money": lambda: round(random.uniform(100, 99999), 2),
    "Currency": lambda: round(random.uniform(100, 99999), 2),
    "Date": lambda: faker.date_between(start_date="-1y", end_date="today").isoformat(),
    "DateTime": lambda: faker.date_time_between(start_date="-1y", end_date="now").strftime("%Y-%m-%d %H:%M"),
    "Phone": lambda: faker.phone_number(),
    "Email": lambda: faker.email(),
    "Checkbox": lambda: random.choice([True, False]),
    "Rating": lambda: random.randint(1, 5),
    "RichText": lambda: faker.paragraph(nb_sentences=3),
}

# 这些字段类型 Faker 无法处理（需要真实 ID）
_UNHANDLEABLE_TYPES = {
    "Collaborator", "Relation", "Attachment", "SubTable",
    "Department", "OrgRole", "Formula", "Summary",
    "AutoNumber", "Concatenate", "DateFormula", "Rollup", "Signature",
}


def _match_exact(field_name: str) -> Optional[callable]:
    """精确匹配字段名。"""
    return _EXACT_NAME_GENERATORS.get(field_name)


def _match_fuzzy(field_name: str) -> Optional[callable]:
    """模糊匹配字段名（contains 任一关键词）。"""
    for keywords, gen in _FUZZY_NAME_RULES:
        for kw in keywords:
            if kw in field_name:
                return gen
    return None


def generate_faker_value(
    field_name: str,
    field_type: str,
    options: list[dict] | None = None,
) -> str | int | float | bool | None:
    """
    按优先级生成 Faker 模拟值：
    1. 字段名精确匹配
    2. 字段名模糊匹配
    3. 单选/多选从 options 中随机选
    4. 字段类型兜底
    """
    # 优先级 1：精确匹配
    gen = _match_exact(field_name)
    if gen is not None:
        return gen()

    # 优先级 2：模糊匹配
    gen = _match_fuzzy(field_name)
    if gen is not None:
        return gen()

    # 优先级 3：单选/多选字段
    if field_type in _OPTION_FIELD_TYPES:
        if options:
            chosen = random.choice(options)
            return chosen.get("key") or chosen.get("value")
        return None

    # 优先级 4：类型兜底
    gen = _TYPE_GENERATORS.get(field_type)
    if gen is not None:
        return gen()

    # 无法处理
    return None


def can_faker_handle(field_name: str, field_type: str) -> bool:
    """
    判断 Faker 是否能处理该字段。
    返回 True 表示可以用 Faker 生成值，不需要 AI 处理。
    """
    # 不可处理的类型直接返回 False
    if field_type in _UNHANDLEABLE_TYPES:
        return False

    # 精确匹配
    if _match_exact(field_name) is not None:
        return True

    # 模糊匹配
    if _match_fuzzy(field_name) is not None:
        return True

    # 单选/多选有选项时可处理（但这里无法判断是否有 options，保守返回 False）
    # 调用方在有 options 信息时可自行判断
    if field_type in _OPTION_FIELD_TYPES:
        return True

    # 类型兜底
    if field_type in _TYPE_GENERATORS:
        return True

    return False
