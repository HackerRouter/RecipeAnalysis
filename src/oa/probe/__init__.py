"""探测层：只看输入长什么样，输出 Profile。"""

from .build import build_profile
from .profile import Profile

__all__ = ["Profile", "build_profile"]
