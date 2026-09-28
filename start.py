"""
StatementParser Unified Launcher
Starts both the FastAPI backend (port 8000) and Next.js frontend (port 3000).
Press Ctrl+C to terminate both servers cleanly.
"""
import os
import sys
import subprocess
import signal
import time

# Remove Windows SSL key log file to avoid SSL issues
os.environ.pop("SSLKEYLOGFILE", None)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_DIR = os.path.join(BASE_DIR, "dashboard")

def main():
    print("=" * 60)
    print("🚀 Starting StatementParser Intelligence Stack")
    print("=" * 60)
    print("  • Backend:  http://localhost:8000  (FastAPI + Uvicorn)")
    print("  • Frontend: http://localhost:3000  (Next.js 15)")
    print("  • Swagger:  http://localhost:8000/docs")
    print("=" * 60)

    # 1. Start FastAPI backend
    print("\n[1/2] Launching FastAPI backend...")
    fastapi_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--reload",
    ]
    fastapi_proc = subprocess.Popen(
        fastapi_cmd,
        cwd=BASE_DIR,
    )

    # Give backend a moment to boot
    time.sleep(2)

    # 2. Start Next.js frontend
    print("\n[2/2] Launching Next.js frontend...")
    npm_cmd = ["npm.cmd" if os.name == "nt" else "npm", "run", "dev"]
    nextjs_proc = subprocess.Popen(
        npm_cmd,
        cwd=DASHBOARD_DIR,
    )

    print("\n✨ Both servers are running. Open http://localhost:3000 in your browser.")
    print("Press Ctrl+C to stop both servers.\n")

    def shutdown(signum, frame):
        print("\n\nShutting down StatementParser servers...")
        try:
            fastapi_proc.terminate()
            nextjs_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Wait for either process to exit
    try:
        while True:
            time.sleep(1)
            if fastapi_proc.poll() is not None:
                print("FastAPI server exited.")
                break
            if nextjs_proc.poll() is not None:
                print("Next.js server exited.")
                break
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
