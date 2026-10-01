'''按配置路径动态导入对象，并提供依赖缺失和类型不符时的诊断信息。'''

from importlib import import_module

MODULE_TO_PACKAGE_HINTS = {
    "langchain_google_genai": "langchain-google-genai",
    "langchain_anthropic": "langchain-anthropic",
    "langchain_openai": "langchain-openai",
    "langchain_deepseek": "langchain-deepseek",
}


def _build_missing_dependency_hint(module_path: str, err: ImportError) -> str:
    '''根据缺失模块推断安装包名称，生成可执行的依赖安装提示。'''
    module_root = module_path.split(".", 1)[0]
    missing_module = getattr(err, "name", None) or module_root

    # 对已知模型集成优先使用对应发行包名，即使报错来自其传递依赖。
    package_name = MODULE_TO_PACKAGE_HINTS.get(module_root)
    if package_name is None:
        package_name = MODULE_TO_PACKAGE_HINTS.get(missing_module, missing_module.replace("_", "-"))

    return f"Missing dependency '{missing_module}'. Install it with `uv add {package_name}` (or `pip install {package_name}`), then restart DeerFlow."


def resolve_variable[T](
    variable_path: str,
    expected_type: type[T] | tuple[type, ...] | None = None,
) -> T:
    '''根据 ``module:attribute`` 路径导入并返回指定对象。

    Resolve a variable from a path.

        Args:
            variable_path: 形如 ``package.module:object_name`` 的导入路径。
            expected_type: 可选的类型或类型元组；提供时会校验对象实例类型。

        Returns:
            解析得到的对象。

        Raises:
            ImportError: 路径无效、模块无法导入或属性不存在时抛出。
            ValueError: 对象类型不符合要求时抛出。
    '''
    try:
        module_path, variable_name = variable_path.rsplit(":", 1)
    except ValueError as err:
        raise ImportError(f"{variable_path} doesn't look like a variable path. Example: parent_package_name.sub_package_name.module_name:variable_name") from err

    try:
        module = import_module(module_path)
    except ImportError as err:
        module_root = module_path.split(".", 1)[0]
        err_name = getattr(err, "name", None)
        if isinstance(err, ModuleNotFoundError) or err_name == module_root:
            hint = _build_missing_dependency_hint(module_path, err)
            raise ImportError(f"Could not import module {module_path}. {hint}") from err
        # 非依赖缺失导致的导入失败保留原始错误原因。
        raise ImportError(f"Error importing module {module_path}: {err}") from err

    try:
        variable = getattr(module, variable_name)
    except AttributeError as err:
        raise ImportError(f"Module {module_path} does not define a {variable_name} attribute/class") from err

    # 如果调用方提供了期望类型，则验证导入对象。
    if expected_type is not None:
        if not isinstance(variable, expected_type):
            type_name = expected_type.__name__ if isinstance(expected_type, type) else " or ".join(t.__name__ for t in expected_type)
            raise ValueError(f"{variable_path} is not an instance of {type_name}, got {type(variable).__name__}")

    return variable


def resolve_class[T](class_path: str, base_class: type[T] | None = None) -> type[T]:
    '''解析类路径，并可选验证该类是否继承指定基类。

    Resolve a class from a module path and class name.

        Args:
            class_path: 形如 ``package.module:ClassName`` 的类路径。
            base_class: 可选的基类约束。

        Returns:
            解析得到的类。

        Raises:
            ImportError: 模块路径无效或类不存在时抛出。
            ValueError: 对象不是类或不满足基类约束时抛出。
    '''
    model_class = resolve_variable(class_path, expected_type=type)

    if not isinstance(model_class, type):
        raise ValueError(f"{class_path} is not a valid class")

    if base_class is not None and not issubclass(model_class, base_class):
        raise ValueError(f"{class_path} is not a subclass of {base_class.__name__}")

    return model_class
