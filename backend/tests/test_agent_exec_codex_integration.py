"""显式开启的真实 Codex CLI 集成测试。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import unittest


@unittest.skipUnless(
    os.getenv("AGENT_EXEC_CODEX_INTEGRATION_ENABLED", "").strip().lower()
    in {"1", "true", "yes", "on"},
    "需要显式设置 AGENT_EXEC_CODEX_INTEGRATION_ENABLED=true 并提供真实 Codex 凭证",
)
class CodexAgentExecIntegrationTest(unittest.TestCase):
    """验证真实 Codex readiness、版本与 read-only sandbox 执行。"""

    @staticmethod
    def _run_read_only_boundary_probe() -> dict[str, str]:
        """使用真实 Codex sandbox 验证只读文件与禁用网络出口。

        Returns:
            sandbox 内 Python 捕获的写入错误与本地 HTTP 访问错误。
        """
        binary = shutil.which("codex")
        if binary is None:
            raise AssertionError("未找到真实 codex CLI")

        class ProbeHandler(BaseHTTPRequestHandler):
            """提供仅监听 127.0.0.1 的探测响应。"""

            def do_GET(self) -> None:
                """返回最小 HTTP 响应。"""
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: object) -> None:
                """关闭默认请求日志。"""

        server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="codex-sandbox-home-") as raw_home, \
                    tempfile.TemporaryDirectory(prefix="codex-sandbox-work-") as raw_work:
                home = Path(raw_home)
                work = Path(raw_work)
                (home / "config.toml").write_text(
                    "\n".join(
                        [
                            'default_permissions = "polyagent-read-only"',
                            "",
                            "[permissions.polyagent-read-only]",
                            'description = "PolyAgent read-only boundary probe"',
                            'extends = ":read-only"',
                            "",
                            "[permissions.polyagent-read-only.network]",
                            "enabled = false",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                script = (
                    "import json,pathlib,urllib.request;"
                    "result={'write_error':'','network_error':''};\n"
                    "try: pathlib.Path('forbidden.txt').write_text('blocked')\n"
                    "except Exception as exc: result['write_error']=str(exc)\n"
                    "try: urllib.request.urlopen("
                    f"'http://127.0.0.1:{server.server_port}/', timeout=3).read()\n"
                    "except Exception as exc: result['network_error']=str(exc)\n"
                    "print('SANDBOX_RESULT='+json.dumps(result))"
                )
                env = os.environ.copy()
                env["CODEX_HOME"] = str(home)
                completed = subprocess.run(
                    [
                        binary,
                        "sandbox",
                        "--permission-profile",
                        "polyagent-read-only",
                        "python",
                        "-c",
                        script,
                    ],
                    cwd=work,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if completed.returncode != 0:
                    raise AssertionError(
                        "Codex sandbox 探测失败："
                        f"{completed.stdout}\n{completed.stderr}"
                    )
                result_line = next(
                    line for line in completed.stdout.splitlines()
                    if line.startswith("SANDBOX_RESULT=")
                )
                return json.loads(result_line.split("=", 1)[1])
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=3)

    def test_real_codex_probe_and_structured_task(self) -> None:
        """真实 provider 必须可探测并完成最小结构化输出任务。"""
        from app.schemas.agent_exec import AgentExecTaskRequest
        from app.services.agent_exec_providers.codex import CodexAgentExecProvider

        provider = CodexAgentExecProvider()
        probe = provider.probe()
        self.assertTrue(probe.readiness.available, probe.readiness.message)
        self.assertEqual(probe.sandbox_mode, "read-only")
        self.assertTrue(probe.version.startswith("codex"))
        self.assertTrue(probe.version_supported, "; ".join(probe.warnings))
        self.assertEqual(len(probe.binary_sha256), 64)

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="agent-exec-codex-") as raw_root:
            workdir = Path(raw_root)
            result = provider.execute(
                task=AgentExecTaskRequest(
                    task_type="structured_file_task",
                    prompt='Return exactly {"summary":"codex integration ready"}.',
                    input_files=[],
                    output_schema={
                        "type": "object",
                        "required": ["summary"],
                        "properties": {"summary": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    timeout_seconds=120,
                ),
                workdir=workdir,
                timeout_seconds=120,
            )
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"summary": "codex integration ready"})

    def test_real_codex_read_only_sandbox_blocks_write_and_local_egress(self) -> None:
        """真实 read-only sandbox 必须拒绝写入和本地网络出口。"""
        result = self._run_read_only_boundary_probe()
        self.assertTrue(result["write_error"], result)
        self.assertTrue(result["network_error"], result)
