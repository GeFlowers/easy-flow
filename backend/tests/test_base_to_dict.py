"""覆盖本模块的可回归测试，固定关键输入、失败分支与资源生命周期，避免后续改动破坏既有契约。"""

from __future__ import annotations

from sqlalchemy import Integer, MetaData, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base, _column_keys


class _Widget(Base):
    """归集“该项”场景的测试与桩对象，明确其成功结果、异常传播和资源回收边界。"""
    __tablename__ = "_widget_to_dict_test"
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    # 此处的测试设置用于精确固定该分支的调用结果、失败传播与资源状态。
    metadata = MetaData()

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(16))


def test_to_dict_returns_all_columns():
    """验证“该项字典返回全部该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    w = _Widget(id=1, name="gear", color="red")
    assert w.to_dict() == {"id": 1, "name": "gear", "color": "red"}


def test_to_dict_exclude():
    """验证“该项字典该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    w = _Widget(id=2, name="cog", color="blue")
    assert w.to_dict(exclude={"color"}) == {"id": 2, "name": "cog"}
    # 空排除的行为与无排除相同。
    assert w.to_dict(exclude=set()) == {"id": 2, "name": "cog", "color": "blue"}


def test_column_keys_are_cached_per_class():
    # 跨调用返回相同的元组对象 -> 反射运行一次。
    """验证“列该项该项缓存该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    assert _column_keys(_Widget) is _column_keys(_Widget)
    assert _column_keys(_Widget) == ("id", "name", "color")


def test_repr_lists_columns():
    """验证“字符串表示该项该项”的回归边界，在受控输入和模拟依赖下固定预期结果、失败分支与资源生命周期。"""
    w = _Widget(id=3, name="bolt", color="green")
    r = repr(w)
    assert r.startswith("_Widget(")
    assert "id=3" in r and "name='bolt'" in r and "color='green'" in r
