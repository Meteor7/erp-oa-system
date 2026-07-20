from pathlib import Path
import tomllib

ROOT = Path(__file__).parents[1]
BASE_IMAGE = "python:3.11-slim"
RUNTIME_REQUIREMENTS = {
    "paddlepaddle==3.3.1",
    "paddleocr==3.7.0",
    "pydantic==2.11.7",
    "Pillow==11.3.0",
    "PyMuPDF==1.26.4",
    "numpy==2.2.6",
    "fastapi==0.116.1",
    "uvicorn==0.35.0",
    "python-multipart==0.0.20",
}
TEST_REQUIREMENTS = {"pytest==8.4.1", "httpx==0.28.1"}


def requirement_lines(filename: str) -> set[str]:
    return {
        line.strip()
        for line in (ROOT / filename).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_runtime_and_test_dependencies_are_fully_locked_and_consistent():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert set(config["project"]["dependencies"]) == RUNTIME_REQUIREMENTS
    assert set(config["project"]["optional-dependencies"]["test"]) == TEST_REQUIREMENTS
    assert requirement_lines("requirements.txt") == RUNTIME_REQUIREMENTS
    assert requirement_lines("requirements-test.txt") == TEST_REQUIREMENTS


def test_dockerfile_has_reproducible_non_root_runtime_and_isolated_test_stage():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith(f"FROM {BASE_IMAGE} AS runtime\n")
    assert "\nFROM runtime AS test\n" in dockerfile
    runtime, test = dockerfile.split("\nFROM runtime AS test\n", maxsplit=1)
    assert "USER ocr" in runtime
    assert runtime.rfind("USER ocr") > runtime.rfind("COPY ")
    assert "EXPOSE 8080" in runtime
    assert "HEALTHCHECK" in runtime
    assert 'invoice_ocr.api:app' in runtime
    assert '"--workers", "1"' in runtime
    assert "requirements-test.txt" not in runtime
    assert "COPY" not in runtime or "tests" not in runtime
    assert "pytest" not in runtime
    assert "requirements-test.txt" in test
    assert "COPY --chown=ocr:ocr tests ./tests" in test
    assert "USER ocr" in test


def test_docker_context_excludes_model_and_sample_artifacts():
    ignored = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert {"models/", "samples/", "output/", ".git/"} <= ignored
