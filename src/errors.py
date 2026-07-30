"""项目异常类型。"""

from __future__ import annotations


class FliceError(Exception):
    """项目基础异常。"""


class InputValidationError(FliceError):
    """输入目录或表单信息校验失败。"""

    def __init__(self, errors: list[str] | str) -> None:
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("输入校验失败：\n" + "\n".join(f"- {item}" for item in self.errors))


class InputPersistenceError(FliceError):
    """标准化后的 input.json 写入失败。"""

    def __init__(self, errors: list[str] | str) -> None:
        if isinstance(errors, str):
            errors = [errors]
        self.errors = list(errors)
        super().__init__("input.json 保存失败：\n" + "\n".join(f"- {item}" for item in self.errors))


class ApiError(FliceError):
    """百度接口调用失败。"""


class BusinessError(FliceError):
    """业务结果不满足流程要求。"""


class AuthenticationRequired(FliceError):
    """需要人工登录或重新登录。"""


class TaskCancelled(FliceError):
    """用户请求安全取消当前任务。"""

    error_code = "task-cancelled"


class PageFlowError(FliceError):
    """页面导航或元素操作失败。"""


class QualificationPendingReview(PageFlowError):
    """目标 URL 的信息资质正在审核，当前不能覆盖处理。"""

    error_code = "qualification-pending-review"


class SchedulerError(FliceError):
    """并发调度状态读取、抢占或持久化失败。"""
