from __future__ import annotations

from thesis_trace.bootstrap.application import compose_application


if __name__ == "__main__":
    import uvicorn

    try:
        application = compose_application("api")
    except Exception as error:
        raise SystemExit("ThesisTrace API configuration or database initialization failed") from error
    uvicorn.run(application, host="0.0.0.0", port=8000)
