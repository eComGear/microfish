"""
MiroFish Backend 启动入口
"""
import os
import sys

# 解决 Windows 控制台中文乱码问题：在所有导入之前设置 UTF-8 编码
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# 验证配置（仅警告，不中断启动 —— 容器环境下退出会被判定为崩溃）
errors = Config.validate()
if errors:
    print("⚠️  配置警告 (Config warnings):", flush=True)
    for err in errors:
        print(f"  - {err}", flush=True)
    print("某些功能可能不可用，请检查环境变量。", flush=True)

# 创建应用（在模块层创建，便于 gunicorn: `gunicorn run:app`）
app = create_app()


# 兜底健康检查端点（如果 app 没有自己的 /health）
try:
    existing = {str(r) for r in app.url_map.iter_rules()}
    if not any("/health" in r for r in existing):
        @app.route("/health")
        def _health():
            return {"status": "ok"}, 200
except Exception as e:
    print(f"无法注册兜底 /health: {e}", flush=True)


def main():
    """开发/容器直接运行入口"""
    host = os.environ.get('HOST') or os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('PORT') or os.environ.get('FLASK_PORT', 5001))
    debug = _bool_env('FLASK_DEBUG', getattr(Config, 'DEBUG', False))

    print(f"🚀 MiroFish backend listening on http://{host}:{port} (debug={debug})", flush=True)
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()

