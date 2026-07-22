"""
应用全局配置加载模块。

从 ``infrastructure/conf/config_{ENV}.yaml`` 读取环境相关配置（ENV 缺省为 local），
将 YAML 顶层键值动态挂到 ``Settings`` 类上，供 ``from infrastructure.conf.settings import settings`` 使用。
"""

import os

import yaml
from dotenv import load_dotenv

from infrastructure.conf.env_interpolate import interpolate_env

# 在读取配置(解析 ${VAR} 占位符)之前先加载 .env——保证任意入口(bot / recall_cli /
# 评测 / 测试)导入本模块时环境变量已就绪，避免因 import 顺序早于各入口的 load_dotenv
# 而报「缺少环境变量」。.env 已被 .gitignore 忽略(密钥不入库)，缺失时用 .env.example 作模板。
load_dotenv()

# 与当前包同目录，即所有 config_*.yaml 所在目录
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env() -> str:
    """
    读取当前运行环境标识。

    Returns:
        环境名：取环境变量 ``ENV``，未设置时返回 ``"local"``。
    """
    env = os.getenv("ENV")
    if not env:
        env = "local"
    return env


def config_yaml_path() -> str:
    """
    当前环境对应的 YAML 配置文件绝对路径。

    Returns:
        ``infrastructure/conf/config_{ENV}.yaml`` 的完整路径字符串。
    """
    env = load_env()
    return os.path.join(_CONFIG_DIR, f"config_{env}.yaml")


def load_settings():
    """
    加载并实例化配置（从 YAML 填充 Settings 类属性）。

    Returns:
        完成 YAML 解析后的 ``Settings`` 类（单例式用法，见模块末尾 ``settings``）。
    """
    env = load_env()
    return Settings.from_yaml(path_name=config_yaml_path(), env=env)


class Settings:
    """
    配置载体类。

    通过 ``from_yaml`` 将 YAML 键值写入类属性，业务代码以 ``settings.xxx`` 访问
    （如 ``settings.qdrant_host``，具体键名由 YAML 决定）。
    """

    @classmethod
    def from_yaml(cls, path_name: str, env: str) -> "Settings":
        """
        从 YAML 文件加载配置并写入本类属性。

        Args:
            path_name: YAML 文件绝对路径。
            env: 环境名（保留参数，便于扩展日志等逻辑）。

        Returns:
            填充完毕的 ``Settings`` 类对象（实际为类本身作命名空间使用）。
        """
        with open(path_name, encoding="utf-8") as fp:
            yc = yaml.load(fp, Loader=yaml.FullLoader)
            yc = interpolate_env(yc)
            for k, v in yc.items():
                setattr(Settings, k, v)

        return cls


# 模块导入时即加载，供全项目复用
settings = load_settings()
