from pathlib import Path
import re
import tomllib


def test_runtime_and_dev_dependencies_are_declared():
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(project_file.read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]
    names = {re.split(r"[<>=!~;\\s]", dependency, maxsplit=1)[0].lower() for dependency in dependencies}

    assert {"pymupdf", "pillow", "pydantic", "paddleocr", "paddlepaddle"} <= names
    assert any(dependency.lower().startswith("pydantic>=2,<3") for dependency in dependencies)
    assert "pytest==8.4.1" in config["project"]["optional-dependencies"]["test"]
