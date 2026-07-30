"""本模块覆盖预配器的行为、边界与回归场景，确保既有契约稳定。"""


# ── _build_volumes ─────────────────────────────────────────────────────


class TestBuildVolumes:
    """集中覆盖当前测试分支与回归边界。"""

    # ── hostPath mode (default) ────────────────────────────────────────

    def test_hostpath_without_legacy_returns_three_volumes(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        assert len(volumes) == 3

    def test_hostpath_skills_public_volume(self, provisioner_module):
        """验证公开 卷在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        pub = volumes[0]
        assert pub.name == "skills-public"
        assert pub.host_path is not None
        assert pub.host_path.path.endswith("/public")
        assert pub.host_path.type == "Directory"
        assert pub.persistent_volume_claim is None

    def test_hostpath_skills_custom_volume(self, provisioner_module):
        """验证卷在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1", user_id="user-7")
        custom = volumes[1]
        assert custom.name == "skills-custom"
        assert custom.host_path is not None
        assert "users/user-7/skills/custom" in custom.host_path.path
        assert custom.host_path.type == "DirectoryOrCreate"

    def test_hostpath_skills_legacy_volume(self, provisioner_module):
        """验证卷在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes(
            "thread-1",
            include_legacy_skills=True,
        )
        legacy = volumes[2]
        assert legacy.name == "skills-legacy"
        assert legacy.host_path is not None
        assert legacy.host_path.path.endswith("/custom")
        assert legacy.host_path.type == "Directory"

    def test_hostpath_without_legacy_has_no_legacy_volume(self, provisioner_module):
        """验证卷在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        assert [volume.name for volume in volumes] == [
            "skills-public",
            "skills-custom",
            "user-data",
        ]

    def test_hostpath_userdata_includes_thread_id(self, provisioner_module):
        """验证会话在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("my-thread-42")
        userdata_vol = volumes[-1]
        path = userdata_vol.host_path.path
        assert "my-thread-42" in path
        assert path.endswith("user-data")
        assert userdata_vol.host_path.type == "DirectoryOrCreate"

    # ── PVC mode (single-volume fallback) ──────────────────────────────

    def test_pvc_returns_two_volumes(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        assert len(volumes) == 2

    def test_skills_pvc_overrides_hostpath(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        skills_vol = volumes[0]
        assert skills_vol.persistent_volume_claim is not None
        assert skills_vol.persistent_volume_claim.claim_name == "my-skills-pvc"
        assert skills_vol.persistent_volume_claim.read_only is True
        assert skills_vol.host_path is None

    def test_userdata_pvc_overrides_hostpath(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.USERDATA_PVC_NAME = "my-userdata-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        userdata_vol = volumes[-1]
        assert userdata_vol.persistent_volume_claim is not None
        assert userdata_vol.persistent_volume_claim.claim_name == "my-userdata-pvc"
        assert userdata_vol.host_path is None

    def test_both_pvc_set(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        assert volumes[0].persistent_volume_claim is not None
        assert volumes[-1].persistent_volume_claim is not None

    def test_pvc_volume_names_are_stable(self, provisioner_module):
        """验证卷在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = "x"
        volumes = provisioner_module._build_volumes("thread-1")
        assert volumes[0].name == "skills"
        assert volumes[-1].name == "user-data"


# ── _build_volume_mounts ───────────────────────────────────────────────


class TestBuildVolumeMounts:
    """集中覆盖当前测试分支与回归边界。"""

    # ── hostPath mode ──────────────────────────────────────────────────

    def test_hostpath_without_legacy_returns_three_mounts(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert len(mounts) == 3

    def test_hostpath_skills_public_mount(self, provisioner_module):
        """验证公开在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].name == "skills-public"
        assert mounts[0].mount_path == "/mnt/skills/public"
        assert mounts[0].read_only is True

    def test_hostpath_skills_custom_mount(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[1].name == "skills-custom"
        assert mounts[1].mount_path == "/mnt/skills/custom"
        assert mounts[1].read_only is True

    def test_hostpath_skills_legacy_mount(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts(
            "thread-1",
            include_legacy_skills=True,
        )
        assert mounts[2].name == "skills-legacy"
        assert mounts[2].mount_path == "/mnt/skills/legacy"
        assert mounts[2].read_only is True

    def test_hostpath_without_legacy_has_no_legacy_mount(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert [mount.name for mount in mounts] == [
            "skills-public",
            "skills-custom",
            "user-data",
        ]

    def test_hostpath_userdata_read_write(self, provisioner_module):
        """验证读取 写入在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        userdata = mounts[-1]
        assert userdata.name == "user-data"
        assert userdata.mount_path == "/mnt/user-data"
        assert userdata.read_only is False

    # ── PVC mode ───────────────────────────────────────────────────────

    def test_pvc_returns_two_mounts(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "x"
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert len(mounts) == 2

    def test_pvc_skills_mount_is_single_root(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "x"
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].mount_path == "/mnt/skills"

    def test_pvc_no_subpath_on_userdata(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.USERDATA_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        userdata_mount = mounts[-1]
        assert userdata_mount.sub_path is None

    def test_skills_pvc_does_not_set_subpath_by_default(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        provisioner_module.SKILLS_PVC_SUBPATH_TEMPLATE = ""
        mounts = provisioner_module._build_volume_mounts("thread-42", user_id="user-7")
        skills_mount = mounts[0]
        assert skills_mount.sub_path is None

    def test_skills_pvc_can_use_user_scoped_subpath_template(self, provisioner_module):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        provisioner_module.SKILLS_PVC_SUBPATH_TEMPLATE = "deer-flow/users/{user_id}/threads/{thread_id}/skills"
        mounts = provisioner_module._build_volume_mounts("thread-42", user_id="user-7")
        skills_mount = mounts[0]
        assert skills_mount.sub_path == "deer-flow/users/user-7/threads/thread-42/skills"

    def test_pvc_sets_user_scoped_subpath(self, provisioner_module):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.USERDATA_PVC_NAME = "my-pvc"
        mounts = provisioner_module._build_volume_mounts("thread-42", user_id="user-7")
        userdata_mount = mounts[-1]
        assert userdata_mount.sub_path == "deer-flow/users/user-7/threads/thread-42/user-data"

    def test_pvc_defaults_to_default_user_subpath(self, provisioner_module):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.USERDATA_PVC_NAME = "my-pvc"
        mounts = provisioner_module._build_volume_mounts("thread-42")
        userdata_mount = mounts[-1]
        assert userdata_mount.sub_path == "deer-flow/users/default/threads/thread-42/user-data"


# ── _build_pod integration ─────────────────────────────────────────────


class TestBuildPodVolumes:
    """集中覆盖当前测试分支与回归边界。"""

    def test_pod_hostpath_without_legacy_has_three_volumes(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.volumes) == 3

    def test_pod_hostpath_without_legacy_has_three_mounts(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.containers[0].volume_mounts) == 3

    def test_pod_hostpath_with_legacy_has_four_volumes(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod(
            "sandbox-1",
            "thread-1",
            include_legacy_skills=True,
        )
        assert len(pod.spec.volumes) == 4

    def test_pod_hostpath_with_legacy_has_four_mounts(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod(
            "sandbox-1",
            "thread-1",
            include_legacy_skills=True,
        )
        assert len(pod.spec.containers[0].volume_mounts) == 4

    def test_pod_pvc_has_two_volumes(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.volumes) == 2

    def test_pod_pvc_has_two_mounts(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.containers[0].volume_mounts) == 2

    def test_pod_pvc_mode_uses_user_scoped_subpath(self, provisioner_module):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        pod = provisioner_module._build_pod("sandbox-1", "thread-1", user_id="user-7")
        assert pod.spec.volumes[0].persistent_volume_claim is not None
        assert pod.spec.volumes[-1].persistent_volume_claim is not None
        userdata_mount = pod.spec.containers[0].volume_mounts[-1]
        assert userdata_mount.sub_path == "deer-flow/users/user-7/threads/thread-1/user-data"

    def test_pod_three_way_skills_mount_paths(self, provisioner_module):
        """验证给定输入和替身状态下的可观察结果符合本用例断言。"""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod(
            "sandbox-1",
            "thread-1",
            include_legacy_skills=True,
        )
        mount_paths = {m.name: m.mount_path for m in pod.spec.containers[0].volume_mounts}
        assert mount_paths["skills-public"] == "/mnt/skills/public"
        assert mount_paths["skills-custom"] == "/mnt/skills/custom"
        assert mount_paths["skills-legacy"] == "/mnt/skills/legacy"

    def test_pod_pvc_mode_can_use_user_scoped_skills_subpath(self, provisioner_module):
        """验证用户在预期条件及边界场景下的可观察行为，防止相关回归。"""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.SKILLS_PVC_SUBPATH_TEMPLATE = "deer-flow/users/{user_id}/threads/{thread_id}/skills"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        pod = provisioner_module._build_pod("sandbox-1", "thread-1", user_id="user-7")
        skills_mount = pod.spec.containers[0].volume_mounts[0]
        assert skills_mount.sub_path == "deer-flow/users/user-7/threads/thread-1/skills"
