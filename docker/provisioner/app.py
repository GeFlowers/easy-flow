"""DeerFlow 沙箱 Provisioner 服务。

该服务会在容器编排集群中按 ``sandbox_id`` 动态创建并管理独立的工作负载和
服务；后端根据配置经由 NodePort 或集群服务 DNS 访问沙箱。
它优先读取挂载的 kubeconfig（``~/.kube/config``），不可用时改用集群内配置。

接口：
    POST   /api/sandboxes              — 创建沙箱工作负载与服务
    DELETE /api/sandboxes/{sandbox_id} — 销毁沙箱工作负载与服务
    GET    /api/sandboxes/{sandbox_id} — 获取沙箱状态与访问地址
    GET    /api/sandboxes              — 列出全部沙箱
    GET    /health                     — 检查 Provisioner 服务健康状态

``docker-compose-dev`` 架构：
    ┌────────────┐  HTTP  ┌─────────────┐  K8s API  ┌──────────────┐
    │ remote     │ ─────▸ │ provisioner │ ────────▸ │  主机集群    │
    │ _backend   │        │ :8002       │           │  接口服务    │
    └────────────┘        └─────────────┘           └──────┬───────┘
                                                           │ creates
                          ┌─────────────┐           ┌──────▼───────┐
                          │   backend   │ ────────▸ │   sandbox    │
                          │             │ direct/DNS│   Pod(s)     │
                          └─────────────┘           └──────────────┘
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager

import urllib3
from fastapi import FastAPI, HTTPException, Request, Response
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from pydantic import BaseModel, Field

# 仅屏蔽 urllib3 的 InsecureRequestWarning。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── 配置（均可由环境变量调整） ──────────────────────────────────────────

K8S_NAMESPACE = os.environ.get("K8S_NAMESPACE", "deer-flow")
SANDBOX_IMAGE = os.environ.get(
    "SANDBOX_IMAGE",
    "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest",
)
SKILLS_HOST_PATH = os.environ.get("SKILLS_HOST_PATH", "/skills")
THREADS_HOST_PATH = os.environ.get("THREADS_HOST_PATH", "/.deer-flow/threads")
DEER_FLOW_HOST_BASE_DIR = os.environ.get("DEER_FLOW_HOST_BASE_DIR", "/.deer-flow")
SKILLS_PVC_NAME = os.environ.get("SKILLS_PVC_NAME", "")
USERDATA_PVC_NAME = os.environ.get("USERDATA_PVC_NAME", "")
SKILLS_PVC_SUBPATH_TEMPLATE = os.environ.get("SKILLS_PVC_SUBPATH_TEMPLATE", "")
SANDBOX_CONTAINER_PORT_RAW = os.environ.get("SANDBOX_CONTAINER_PORT", "8080")
SANDBOX_SERVICE_TYPE = os.environ.get("SANDBOX_SERVICE_TYPE", "NodePort")
try:
    SANDBOX_CONTAINER_PORT = int(SANDBOX_CONTAINER_PORT_RAW)
except ValueError as exc:
    raise RuntimeError(f"Invalid SANDBOX_CONTAINER_PORT={SANDBOX_CONTAINER_PORT_RAW!r}; expected an integer TCP port") from exc
if not (1 <= SANDBOX_CONTAINER_PORT <= 65535):
    raise RuntimeError(f"Invalid SANDBOX_CONTAINER_PORT={SANDBOX_CONTAINER_PORT}; expected a value in [1, 65535]")
if SANDBOX_SERVICE_TYPE not in {"NodePort", "ClusterIP"}:
    raise RuntimeError(f"Invalid SANDBOX_SERVICE_TYPE={SANDBOX_SERVICE_TYPE!r}; expected 'NodePort' or 'ClusterIP'")
SAFE_THREAD_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
SAFE_USER_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
DEFAULT_USER_ID = "default"

# Provisioner 容器内 kubeconfig 的路径；通常将主机的 ``~/.kube/config`` 挂载至此。
KUBECONFIG_PATH = os.environ.get("KUBECONFIG_PATH", "/root/.kube/config")
PROVISIONER_API_KEY = os.environ.get("PROVISIONER_API_KEY", "")

# 后端连接 NodePort Service 时使用的主机名或 IP；macOS Docker Desktop 通常为
# ``host.docker.internal``，Linux 可使用主机局域网 IP；ClusterIP 模式忽略此项。
NODE_HOST = os.environ.get("NODE_HOST", "host.docker.internal")


def join_host_path(base: str, *parts: str) -> str:
    """按宿主机路径风格拼接片段，兼容 Windows 盘符、UNC 路径与 POSIX 路径。"""
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        from pathlib import PureWindowsPath

        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    from pathlib import Path

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


# ── Kubernetes 客户端初始化 ─────────────────────────────────────────────

core_v1: k8s_client.CoreV1Api | None = None


def _init_k8s_client() -> k8s_client.CoreV1Api:
    """加载 Kubernetes 配置并返回 ``CoreV1Api``。

    优先使用挂载的 kubeconfig，文件不存在时回退至集群内配置。若设置
    ``K8S_API_SERVER``，会覆盖 kubeconfig 中的地址以便容器访问宿主集群；本地
    自签名证书场景会关闭证书校验，配置加载失败会抛出带上下文的 ``RuntimeError``。
    """
    if os.path.exists(KUBECONFIG_PATH):
        if os.path.isdir(KUBECONFIG_PATH):
            raise RuntimeError(f"KUBECONFIG_PATH points to a directory, expected a file: {KUBECONFIG_PATH}")
        try:
            k8s_config.load_kube_config(config_file=KUBECONFIG_PATH)
            logger.info(f"Loaded kubeconfig from {KUBECONFIG_PATH}")
        except Exception as exc:
            raise RuntimeError(f"Failed to load kubeconfig from {KUBECONFIG_PATH}: {exc}") from exc
    else:
        logger.warning(f"Kubeconfig not found at {KUBECONFIG_PATH}; trying in-cluster config")
        try:
            k8s_config.load_incluster_config()
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Kubernetes client. No kubeconfig at {KUBECONFIG_PATH}, and in-cluster config is unavailable: {exc}") from exc

    # 容器内 ``localhost`` 指向自身；允许用环境变量改写 kubeconfig 的 API 地址以连接宿主集群。
    k8s_api_server = os.environ.get("K8S_API_SERVER")
    if k8s_api_server:
        configuration = k8s_client.Configuration.get_default_copy()
        configuration.host = k8s_api_server
        # 本地 Kubernetes 集群常使用自签名证书。
        configuration.verify_ssl = False
        api_client = k8s_client.ApiClient(configuration)
        return k8s_client.CoreV1Api(api_client)

    return k8s_client.CoreV1Api()


def _wait_for_kubeconfig(timeout: int = 30) -> None:
    """在超时前等待有效 kubeconfig 文件，超时后记录告警并让后续逻辑尝试集群内配置。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(KUBECONFIG_PATH):
            if os.path.isfile(KUBECONFIG_PATH):
                logger.info(f"Found kubeconfig file at {KUBECONFIG_PATH}")
                return
            if os.path.isdir(KUBECONFIG_PATH):
                raise RuntimeError(f"Kubeconfig path is a directory. Please mount a kubeconfig file at {KUBECONFIG_PATH}.")
            raise RuntimeError(f"Kubeconfig path exists but is not a regular file: {KUBECONFIG_PATH}")
        logger.info(f"Waiting for kubeconfig at {KUBECONFIG_PATH} …")
        time.sleep(2)
    logger.warning(f"Kubeconfig not found at {KUBECONFIG_PATH} after {timeout}s; will attempt in-cluster Kubernetes config")


def _ensure_namespace() -> None:
    """确保目标命名空间存在；仅在 API 返回 404 时创建，其他 Kubernetes 错误原样上抛。"""
    try:
        core_v1.read_namespace(K8S_NAMESPACE)
        logger.info(f"Namespace '{K8S_NAMESPACE}' already exists")
    except ApiException as exc:
        if exc.status == 404:
            ns = k8s_client.V1Namespace(
                metadata=k8s_client.V1ObjectMeta(
                    name=K8S_NAMESPACE,
                    labels={
                        "app.kubernetes.io/name": "deer-flow",
                        "app.kubernetes.io/component": "sandbox",
                    },
                )
            )
            core_v1.create_namespace(ns)
            logger.info(f"Created namespace '{K8S_NAMESPACE}'")
        else:
            raise


# ── FastAPI 生命周期 ────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """管理 Provisioner 生命周期中的 Kubernetes 客户端初始化。"""
    global core_v1
    _wait_for_kubeconfig()
    core_v1 = _init_k8s_client()
    _ensure_namespace()
    logger.info("Provisioner is ready (using host Kubernetes)")
    yield


app = FastAPI(title="DeerFlow Sandbox Provisioner", lifespan=lifespan)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    """验证 ``/api/`` 请求携带的 Provisioner 接口密钥。"""
    if request.url.path.startswith("/api/"):
        key = request.headers.get("X-API-Key", "")
        if not PROVISIONER_API_KEY or not secrets.compare_digest(key, PROVISIONER_API_KEY):
            logger.warning("provisioner auth rejected: %s %s", request.method, request.url.path)
            return Response(status_code=401, content="Unauthorized")
    return await call_next(request)


# ── 请求与响应模型 ──────────────────────────────────────────────────────


class CreateSandboxRequest(BaseModel):
    """创建沙箱接口的请求模型。"""
    sandbox_id: str
    thread_id: str = Field(pattern=SAFE_THREAD_ID_PATTERN)
    user_id: str = Field(default=DEFAULT_USER_ID, pattern=SAFE_USER_ID_PATTERN)
    include_legacy_skills: bool = False


class SandboxResponse(BaseModel):
    """沙箱接口的响应模型。"""
    sandbox_id: str
    sandbox_url: str
    status: str


# ── Kubernetes 资源构造辅助函数 ─────────────────────────────────────────


def _pod_name(sandbox_id: str) -> str:
    """生成沙箱 Pod 的 Kubernetes 名称。"""
    return f"sandbox-{sandbox_id}"


def _svc_name(sandbox_id: str) -> str:
    """生成沙箱 Service 的 Kubernetes 名称。"""
    return f"sandbox-{sandbox_id}-svc"


def _sandbox_url(sandbox_id: str, node_port: int | None = None) -> str:
    """按 Service 模式生成后端访问 URL；NodePort 模式必须提供已分配端口。"""
    if SANDBOX_SERVICE_TYPE == "ClusterIP":
        return f"http://{_svc_name(sandbox_id)}.{K8S_NAMESPACE}.svc.cluster.local:{SANDBOX_CONTAINER_PORT}"
    if node_port is None:
        raise RuntimeError("node_port is required when SANDBOX_SERVICE_TYPE=NodePort")
    return f"http://{NODE_HOST}:{node_port}"


def _build_volumes(
    thread_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    include_legacy_skills: bool = False,
) -> list[k8s_client.V1Volume]:
    """构造 Pod 卷列表，在 PVC 与安全的宿主机目录布局之间切换。

    非 PVC 模式将公共、用户自定义及可选旧版技能分卷挂载，使
    ``/mnt/skills/{public,custom,legacy}/`` 与本地沙箱路径契约一致；线程数据
    按 ``thread_id`` 隔离。PVC 暂不支持三路 ``subPath``，因此保持兼容的单卷挂载。
    """
    volumes: list[k8s_client.V1Volume] = []

    # ── 技能卷 ───────────────────────────────────────────────────────

    if SKILLS_PVC_NAME:
        # PVC 尚不支持三路 subPath，回退为单卷以保持旧部署兼容。
        logger.warning("SKILLS_PVC_NAME is set — three-way skills layout is not supported in PVC mode yet; falling back to single /mnt/skills mount")
        volumes.append(
            k8s_client.V1Volume(
                name="skills",
                persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=SKILLS_PVC_NAME,
                    read_only=True,
                ),
            )
        )
    else:
        # 宿主机路径模式采用三路技能布局。
        public_path = join_host_path(SKILLS_HOST_PATH, "public")
        volumes.append(
            k8s_client.V1Volume(
                name="skills-public",
                host_path=k8s_client.V1HostPathVolumeSource(
                    path=public_path,
                    type="Directory",
                ),
            )
        )

        user_custom_path = join_host_path(
            DEER_FLOW_HOST_BASE_DIR,
            "users",
            user_id,
            "skills",
            "custom",
        )
        volumes.append(
            k8s_client.V1Volume(
                name="skills-custom",
                host_path=k8s_client.V1HostPathVolumeSource(
                    path=user_custom_path,
                    type="DirectoryOrCreate",
                ),
            )
        )

        if include_legacy_skills:
            legacy_path = join_host_path(SKILLS_HOST_PATH, "custom")
            volumes.append(
                k8s_client.V1Volume(
                    name="skills-legacy",
                    host_path=k8s_client.V1HostPathVolumeSource(
                        path=legacy_path,
                        type="Directory",
                    ),
                )
            )

    # ── 用户数据卷 ───────────────────────────────────────────────────

    if USERDATA_PVC_NAME:
        userdata_vol = k8s_client.V1Volume(
            name="user-data",
            persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                claim_name=USERDATA_PVC_NAME,
            ),
        )
    else:
        userdata_vol = k8s_client.V1Volume(
            name="user-data",
            host_path=k8s_client.V1HostPathVolumeSource(
                path=join_host_path(THREADS_HOST_PATH, thread_id, "user-data"),
                type="DirectoryOrCreate",
            ),
        )

    volumes.append(userdata_vol)
    return volumes


def _build_volume_mounts(
    thread_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    include_legacy_skills: bool = False,
) -> list[k8s_client.V1VolumeMount]:
    """构造与技能卷对应的容器挂载点，并保留用户和线程隔离边界。

    非 PVC 模式挂载到 ``/mnt/skills/{public,custom,legacy}/``，满足
    ``Skill.get_container_path()`` 的分类路径契约；PVC 模式使用单个
    ``/mnt/skills``，并可由 ``SKILLS_PVC_SUBPATH_TEMPLATE`` 进一步限定范围。
    """
    mounts: list[k8s_client.V1VolumeMount] = []

    if SKILLS_PVC_NAME:
        skills_mount = k8s_client.V1VolumeMount(
            name="skills",
            mount_path="/mnt/skills",
            read_only=True,
        )
        if SKILLS_PVC_SUBPATH_TEMPLATE:
            skills_mount.sub_path = SKILLS_PVC_SUBPATH_TEMPLATE.format(
                user_id=user_id,
                thread_id=thread_id,
            )
        mounts.append(skills_mount)
    else:
        mounts.extend(
            [
                k8s_client.V1VolumeMount(
                    name="skills-public",
                    mount_path="/mnt/skills/public",
                    read_only=True,
                ),
                k8s_client.V1VolumeMount(
                    name="skills-custom",
                    mount_path="/mnt/skills/custom",
                    read_only=True,
                ),
            ]
        )
        if include_legacy_skills:
            mounts.append(
                k8s_client.V1VolumeMount(
                    name="skills-legacy",
                    mount_path="/mnt/skills/legacy",
                    read_only=True,
                )
            )

    userdata_mount = k8s_client.V1VolumeMount(
        name="user-data",
        mount_path="/mnt/user-data",
        read_only=False,
    )
    if USERDATA_PVC_NAME:
        userdata_mount.sub_path = f"deer-flow/users/{user_id}/threads/{thread_id}/user-data"
    mounts.append(userdata_mount)

    return mounts


def _build_pod(
    sandbox_id: str,
    thread_id: str,
    user_id: str = DEFAULT_USER_ID,
    *,
    include_legacy_skills: bool = False,
) -> k8s_client.V1Pod:
    """为单个沙箱构造 Pod 清单，包含受限容器、健康探针、资源限额及隔离卷。"""
    return k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(
            name=_pod_name(sandbox_id),
            namespace=K8S_NAMESPACE,
            labels={
                "app": "deer-flow-sandbox",
                "sandbox-id": sandbox_id,
                "app.kubernetes.io/name": "deer-flow",
                "app.kubernetes.io/component": "sandbox",
            },
        ),
        spec=k8s_client.V1PodSpec(
            containers=[
                k8s_client.V1Container(
                    name="sandbox",
                    image=SANDBOX_IMAGE,
                    image_pull_policy="IfNotPresent",
                    ports=[
                        k8s_client.V1ContainerPort(
                            name="http",
                            container_port=SANDBOX_CONTAINER_PORT,
                            protocol="TCP",
                        )
                    ],
                    readiness_probe=k8s_client.V1Probe(
                        http_get=k8s_client.V1HTTPGetAction(
                            path="/v1/sandbox",
                            port=SANDBOX_CONTAINER_PORT,
                        ),
                        initial_delay_seconds=5,
                        period_seconds=5,
                        timeout_seconds=3,
                        failure_threshold=3,
                    ),
                    liveness_probe=k8s_client.V1Probe(
                        http_get=k8s_client.V1HTTPGetAction(
                            path="/v1/sandbox",
                            port=SANDBOX_CONTAINER_PORT,
                        ),
                        initial_delay_seconds=10,
                        period_seconds=10,
                        timeout_seconds=3,
                        failure_threshold=3,
                    ),
                    resources=k8s_client.V1ResourceRequirements(
                        requests={
                            "cpu": "100m",
                            "memory": "256Mi",
                            "ephemeral-storage": "500Mi",
                        },
                        limits={
                            "cpu": "1000m",
                            "memory": "1Gi",
                            "ephemeral-storage": "500Mi",
                        },
                    ),
                    volume_mounts=_build_volume_mounts(
                        thread_id,
                        user_id=user_id,
                        include_legacy_skills=include_legacy_skills,
                    ),
                    security_context=k8s_client.V1SecurityContext(
                        privileged=False,
                        allow_privilege_escalation=True,
                    ),
                )
            ],
            volumes=_build_volumes(
                thread_id,
                user_id=user_id,
                include_legacy_skills=include_legacy_skills,
            ),
            restart_policy="Always",
        ),
    )


def _build_service(sandbox_id: str) -> k8s_client.V1Service:
    """按配置的访问模式构造仅选择对应 ``sandbox-id`` 工作负载的 TCP 服务清单。"""
    return k8s_client.V1Service(
        metadata=k8s_client.V1ObjectMeta(
            name=_svc_name(sandbox_id),
            namespace=K8S_NAMESPACE,
            labels={
                "app": "deer-flow-sandbox",
                "sandbox-id": sandbox_id,
                "app.kubernetes.io/name": "deer-flow",
                "app.kubernetes.io/component": "sandbox",
            },
        ),
        spec=k8s_client.V1ServiceSpec(
            type=SANDBOX_SERVICE_TYPE,
            ports=[
                k8s_client.V1ServicePort(
                    name="http",
                    port=SANDBOX_CONTAINER_PORT,
                    target_port=SANDBOX_CONTAINER_PORT,
                    protocol="TCP",
                )
            ],
            selector={
                "sandbox-id": sandbox_id,
            },
        ),
    )


def _url_from_service(svc, sandbox_id: str) -> str | None:
    """从已读取的 Service 解析后端可访问 URL；端口尚未分配时返回 ``None``。"""
    if SANDBOX_SERVICE_TYPE == "ClusterIP":
        return _sandbox_url(sandbox_id)

    for port in svc.spec.ports or []:
        if port.name == "http" and port.node_port:
            return _sandbox_url(sandbox_id, node_port=port.node_port)
    return None


def _sandbox_access_url(sandbox_id: str, *, tolerate_read_errors: bool = False) -> str | None:
    """读取沙箱 Service 并在可访问时返回 URL；可容忍的短暂读取错误记录后返回空值。"""
    try:
        svc = core_v1.read_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            return None
        if tolerate_read_errors and exc.status not in {401, 403}:
            logger.warning(
                "Transient error reading Service %s: status=%s reason=%s",
                _svc_name(sandbox_id),
                exc.status,
                exc.reason,
            )
            return None
        raise

    return _url_from_service(svc, sandbox_id)


def _get_pod_phase(sandbox_id: str) -> str:
    """返回 Pod 生命周期阶段；资源不存在时返回 ``NotFound``，避免将其误作运行状态。"""
    try:
        pod = core_v1.read_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
        return pod.status.phase or "Unknown"
    except ApiException:
        return "NotFound"


# ── API 端点 ────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """返回进程存活状态，供负载均衡器与部署探针检查。"""
    return {"status": "ok"}


@app.post("/api/sandboxes", response_model=SandboxResponse)
def create_sandbox(req: CreateSandboxRequest):
    """为请求的沙箱创建 Pod 和 Service，并在资源已存在时保持幂等。

    ``thread_id`` 与 ``user_id`` 已由模型正则约束，用于隔离数据和自定义技能。创建
    Service 失败会尽力删除刚创建的 Pod；等候访问地址超时或 Kubernetes 操作失败时，
    向调用方返回明确的 HTTP 500。
    """
    sandbox_id = req.sandbox_id
    thread_id = req.thread_id
    user_id = req.user_id
    include_legacy_skills = req.include_legacy_skills

    logger.info(
        "Received request to create sandbox '%s' for thread '%s' user '%s' include_legacy_skills=%s",
        sandbox_id,
        thread_id,
        user_id,
        include_legacy_skills,
    )

    # ── 快速路径：已有沙箱直接返回 ───────────────────────────────────
    existing_url = _sandbox_access_url(sandbox_id, tolerate_read_errors=True)
    if existing_url:
        return SandboxResponse(
            sandbox_id=sandbox_id,
            sandbox_url=existing_url,
            status=_get_pod_phase(sandbox_id),
        )

    # ── 创建 Pod ─────────────────────────────────────────────────────
    try:
        core_v1.create_namespaced_pod(
            K8S_NAMESPACE,
            _build_pod(
                sandbox_id,
                thread_id,
                user_id=user_id,
                include_legacy_skills=include_legacy_skills,
            ),
        )
        logger.info(f"Created Pod {_pod_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 409:  # 409 = AlreadyExists
            raise HTTPException(status_code=500, detail=f"Pod creation failed: {exc.reason}")

    # ── 创建 Service ─────────────────────────────────────────────────
    try:
        core_v1.create_namespaced_service(K8S_NAMESPACE, _build_service(sandbox_id))
        logger.info(f"Created Service {_svc_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 409:
            # Service 创建失败时回滚本次创建的 Pod，避免残留孤儿资源。
            try:
                core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
            except ApiException:
                pass
            raise HTTPException(status_code=500, detail=f"Service creation failed: {exc.reason}")

    # ── 等待 Service 获得可用访问地址 ─────────────────────────────────
    sandbox_url: str | None = None
    for _ in range(20):
        sandbox_url = _sandbox_access_url(sandbox_id, tolerate_read_errors=True)
        if sandbox_url:
            break
        time.sleep(0.5)

    if not sandbox_url:
        raise HTTPException(status_code=500, detail="Service access URL was not available in time")

    return SandboxResponse(
        sandbox_id=sandbox_id,
        sandbox_url=sandbox_url,
        status=_get_pod_phase(sandbox_id),
    )


@app.delete("/api/sandboxes/{sandbox_id}")
def destroy_sandbox(sandbox_id: str):
    """删除沙箱 Service 与 Pod；404 视为幂等成功，其余部分清理失败会汇总后返回 500。"""
    errors: list[str] = []

    # 先删除 Service，避免新请求继续路由到正在销毁的 Pod。
    try:
        core_v1.delete_namespaced_service(_svc_name(sandbox_id), K8S_NAMESPACE)
        logger.info(f"Deleted Service {_svc_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 404:
            errors.append(f"service: {exc.reason}")

    # 再删除 Pod；两步均尝试执行以报告完整的清理结果。
    try:
        core_v1.delete_namespaced_pod(_pod_name(sandbox_id), K8S_NAMESPACE)
        logger.info(f"Deleted Pod {_pod_name(sandbox_id)}")
    except ApiException as exc:
        if exc.status != 404:
            errors.append(f"pod: {exc.reason}")

    if errors:
        raise HTTPException(status_code=500, detail=f"Partial cleanup: {', '.join(errors)}")

    return {"ok": True, "sandbox_id": sandbox_id}


@app.get("/api/sandboxes/{sandbox_id}", response_model=SandboxResponse)
def get_sandbox(sandbox_id: str):
    """返回指定沙箱的当前访问地址和 Pod 状态；Service 不存在或无地址时返回 404。"""
    sandbox_url = _sandbox_access_url(sandbox_id)
    if not sandbox_url:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")

    return SandboxResponse(
        sandbox_id=sandbox_id,
        sandbox_url=sandbox_url,
        status=_get_pod_phase(sandbox_id),
    )


@app.get("/api/sandboxes")
def list_sandboxes():
    """列出命名空间内带沙箱标签且已具有可访问地址的所有 Service。"""
    try:
        services = core_v1.list_namespaced_service(
            K8S_NAMESPACE,
            label_selector="app=deer-flow-sandbox",
        )
    except ApiException as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list services: {exc.reason}")

    sandboxes: list[SandboxResponse] = []
    for svc in services.items:
        sid = (svc.metadata.labels or {}).get("sandbox-id")
        if not sid:
            continue
        sandbox_url = _url_from_service(svc, sid)
        if not sandbox_url:
            continue
        sandboxes.append(
            SandboxResponse(
                sandbox_id=sid,
                sandbox_url=sandbox_url,
                status=_get_pod_phase(sid),
            )
        )

    return {"sandboxes": sandboxes, "count": len(sandboxes)}
