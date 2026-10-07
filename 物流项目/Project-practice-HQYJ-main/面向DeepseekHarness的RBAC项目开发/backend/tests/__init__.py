"""测试包。

加这个 __init__.py 是为了让 `from tests.conftest import ...` 这种绝对导入成立
（没有它时，conftest 只能靠 pytest 的 rootdir 机制被加载，不能被普通 import 引用）。
"""
